"""Turn a configured source into NewsItems, and never let one kill the run.

Layer 2. Two halves of one concern:

- `parse()` maps a response body onto the NewsItem shape, dispatching on the
  **declared** format rather than on the content type - HN Algolia answers
  `application/json` for what the config already told us is JSON, and a source
  that lies about its type must not silently produce nothing.
- `read_source()` is the single place a source failure is caught. `search.py`
  calls it too, so the guard lives once instead of in every caller.

Contract: docs/memory-ai/data/news-sources.md (field mapping),
docs/memory-ai/behavior/news-search.md (stages 2 and 3)
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
import logging

import feedparser

from ..item import new_item

__all__ = ["parse", "read_source", "read_fixed_feeds", "FORMATS", "DEFAULT_FORMAT"]

log = logging.getLogger("news_radar.fetch.feeds")

# RSS and Atom are one branch on purpose: feedparser normalises both into
# `entries[]` with the same attribute names, and twenty years of malformed
# feeds is exactly what it exists to absorb.
FORMATS = ("rss", "atom", "hn_algolia_json")
DEFAULT_FORMAT = "rss"

HN_ITEM_URL = "https://news.ycombinator.com/item?id={}"


def _utc(struct_time):
    """A feedparser time tuple - already UTC - as an aware datetime."""
    if not struct_time:
        return None
    return dt.datetime.fromtimestamp(calendar.timegm(struct_time), tz=dt.timezone.utc)


def _iso_utc(text):
    """An RFC 3339 timestamp as an aware UTC datetime, or None."""
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # Algolia documents UTC and sends the Z. A bare timestamp is read as
        # UTC rather than as the host's local time, which would make freshness
        # depend on where the container happens to run.
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _entry_url(entry):
    """The story link: the alternate link for Atom, `link` for RSS."""
    for link in entry.get("links") or ():
        if link.get("rel") == "alternate" and link.get("href"):
            return link["href"]
    return entry.get("link") or ""


def parse(body, fmt, source_id, keyword_group=None, fetched_at=None):
    """Map a response body onto NewsItems. Never raises on bad content.

    A body that is not a feed - an error page, a truncated download, a throttled
    query answering with nothing - yields an empty list. Only an unknown format
    raises, because that is a config mistake and not a source having a bad day.
    """
    fetched_at = fetched_at or dt.datetime.now(dt.timezone.utc)
    fmt = (fmt or DEFAULT_FORMAT).lower()
    if fmt not in FORMATS:
        raise ValueError("unknown source format {!r}, expected one of {}".format(
            fmt, ", ".join(FORMATS)))

    if fmt == "hn_algolia_json":
        raw = _algolia_entries(body, source_id)
    else:
        raw = _feed_entries(body, source_id)

    items = []
    for title, url, external_id, published_at in raw:
        try:
            items.append(new_item(
                title=title, url=url, source_id=source_id,
                external_id=external_id, published_at=published_at,
                keyword_group=keyword_group, fetched_at=fetched_at))
        except ValueError:
            # No title: nothing to display and nothing to match on. Counted in
            # debug rather than silently vanishing, so a feed that suddenly
            # ships titleless entries is visible.
            log.debug("%s: dropped an entry with no title (%s)", source_id, url)
    return items


def _feed_entries(body, source_id):
    parsed = feedparser.parse(body)
    if parsed.get("bozo") and not parsed.get("entries"):
        log.debug("%s: not a parseable feed (%s)", source_id,
                  parsed.get("bozo_exception"))
        return []
    for entry in parsed.get("entries") or ():
        url = _entry_url(entry)
        yield (
            entry.get("title") or "",
            url,
            entry.get("id") or entry.get("guid") or "",
            _utc(entry.get("published_parsed") or entry.get("updated_parsed")),
        )


def _algolia_entries(body, source_id):
    try:
        payload = json.loads(body)
        hits = payload["hits"]
    except (ValueError, TypeError, KeyError) as exc:
        log.debug("%s: not an Algolia response (%s)", source_id, exc)
        return
    for hit in hits:
        object_id = str(hit.get("objectID") or "")
        yield (
            hit.get("title") or "",
            # Ask HN and Show HN text posts carry no outbound url. Without the
            # permalink fallback they would reach the report with no link at
            # all, which is a headline nobody can open.
            hit.get("url") or (HN_ITEM_URL.format(object_id) if object_id else ""),
            object_id,
            _iso_utc(hit.get("created_at")),
        )


def read_source(fetcher, source, keyword_group=None, fetched_at=None):
    """Fetch and parse one source. Returns (items, error) - it never raises.

    `error` is `(source_id, reason)` when the source could not be read at all,
    and `None` otherwise. This is the only place a source failure is caught:
    one dead feed logs a line and the run keeps the other twenty-one.
    """
    source_id = source.get("id") or "?"
    url = source.get("url") or ""
    fmt = source.get("format") or DEFAULT_FORMAT

    try:
        body = fetcher.get(url)
        items = parse(body, fmt, source_id, keyword_group=keyword_group,
                      fetched_at=fetched_at)
    except Exception as exc:  # noqa: BLE001 - isolation is the whole point
        log.warning("%s: %s", source_id, exc)
        return [], (source_id, str(exc))

    if not items:
        # Google News answers a throttled query with an empty feed rather than
        # an error. Calling that a failure would put a red entry in the run for
        # a source that is merely quiet - but saying nothing at all is how a
        # feed that has silently died goes unnoticed for a week.
        log.info("%s: no items (source is quiet, throttled, or has changed shape)",
                 source_id)
    else:
        log.debug("%s: %d item(s)", source_id, len(items))
    return items, None


def read_fixed_feeds(fetcher, cfg, fetched_at=None):
    """Every enabled `feeds[]` entry, fetched in order. Returns (items, errors)."""
    items = []
    errors = []
    for source in cfg.enabled_feeds():
        got, error = read_source(fetcher, source, fetched_at=fetched_at)
        items.extend(got)
        if error:
            errors.append(error)
    return items, errors
