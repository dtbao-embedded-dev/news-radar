"""Turn a configured source into NewsItems, and never let one kill the run.

Layer 2. Two halves of one concern:

- `parse()` maps a response body onto the NewsItem shape, dispatching on the
  **declared** format rather than on the content type - HN Algolia answers
  `application/json` for what the config already told us is JSON, and a source
  that lies about its type must not silently produce nothing.
- `read_source()` is the single place a source failure is caught. `search.py`
  calls it too, so the guard lives once instead of in every caller.
- `read_sources()` sends a whole plan - fixed feeds and search queries alike -
  host-interleaved, and stops asking a host once it has failed for good.

Contract: docs/memory-ai/data/news-sources.md (field mapping),
docs/memory-ai/behavior/news-search.md (stages 2 and 3)
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
import logging
from urllib.parse import urlsplit

import feedparser

from ..item import new_item
from .http import RETRY_STATUSES, HttpError

__all__ = ["parse", "read_source", "read_sources", "collect", "fixed_plan",
           "read_fixed_feeds", "FORMATS", "DEFAULT_FORMAT"]

log = logging.getLogger("news_radar.fetch.feeds")

# RSS and Atom are one branch on purpose: feedparser normalises both into
# `entries[]` with the same attribute names, and twenty years of malformed
# feeds is exactly what it exists to absorb.
FORMATS = ("rss", "atom", "hn_algolia_json")
DEFAULT_FORMAT = "rss"

HN_ITEM_URL = "https://news.ycombinator.com/item?id={}"

# Consecutive for-good failures that take a host out of the rest of a cycle.
# Two, not one: `search.py`'s own contract is that one throttled query must not
# cost the other groups their results, and a single 429 can be a blip. Two in a
# row, after the transport's retries on each, is the host saying no - and it
# bounds a throttled Google News at two stalled queries instead of thirteen.
HOST_STRIKES = 2


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
    for title, url, external_id, published_at, excerpt in raw:
        try:
            items.append(new_item(
                title=title, url=url, source_id=source_id,
                external_id=external_id, published_at=published_at,
                keyword_group=keyword_group, fetched_at=fetched_at,
                excerpt=excerpt))
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
            _entry_excerpt(entry),
        )


def _entry_excerpt(entry):
    """The entry's own description, as markup. `new_item()` strips and caps it.

    feedparser normalises RSS `<description>`, Atom `<summary>` and Atom
    `<content>` onto two attributes, and they disagree about which carries the
    real text: a full-text Atom feed puts the article in `content` and a one-
    line teaser in `summary`, while most RSS feeds have only `summary`. Longest
    wins rather than first, because the summary a model is written from should
    be the fullest text the feed handed over.

    A feed that carries neither yields `""`, which is the normal case for
    Reddit-style link posts - and the reason nothing downstream may require it.
    """
    texts = [entry.get("summary") or ""]
    for block in entry.get("content") or ():
        texts.append((block or {}).get("value") or "")
    return max(texts, key=len)


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
            # Only Ask HN / Show HN posts carry one; a plain link submission has
            # nothing but its title, which is the honest empty case.
            hit.get("story_text") or "",
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


class _HostBreaker:
    """The fetcher, minus every host that has already failed for good this cycle.

    "For good" is the retryable class - 429, 5xx, timeout, DNS, refused - and
    only once the transport has spent its own retries on it. Without this, a
    Google News that answers 429 makes each of its remaining queries retry and
    wait as well, up to `RETRY_AFTER_MAX` apiece, and the cycle stalls past its
    own interval for results that are not coming. A 403 or a 404 is a verdict
    on one url and leaves the host alone: Reddit refuses one path and serves
    the next.

    It takes `HOST_STRIKES` of them in a row; an answer in between resets the
    count. A skipped request still raises, so `read_source()` records it as
    that source's own error and a dead host stays visible in the count lines
    and in `_dead_sources()`. Scoped to one `read_sources()` call, so the next
    cycle asks again.
    """

    def __init__(self, fetcher):
        self._fetcher = fetcher
        self._strikes = {}  # hostname -> consecutive for-good failures
        self._down = {}     # hostname -> the failure that took it out

    def ready_in(self, host):
        if host in self._down:
            return 0.0  # costs nothing to send, so it never holds up the plan
        ready_in = getattr(self._fetcher, "ready_in", None)
        return ready_in(host) if ready_in else 0.0

    def get(self, url):
        host = urlsplit(url).hostname
        if host in self._down:
            raise HttpError("skipped: {} already failed this cycle ({})".format(
                host, self._down[host]), url=url)
        try:
            body = self._fetcher.get(url)
        except HttpError as exc:
            if host and (exc.status is None or exc.status in RETRY_STATUSES):
                self._strikes[host] = self._strikes.get(host, 0) + 1
                if self._strikes[host] >= HOST_STRIKES:
                    self._down[host] = str(exc)
                    log.warning("%s failed %d request(s) in a row (%s); its "
                                "remaining requests are skipped this cycle",
                                host, self._strikes[host], exc)
            raise
        self._strikes.pop(host, None)
        return body


def _next_host(lanes, fetcher):
    """The host to ask next: the busiest one that is free, else the soonest free.

    The busiest host is the critical path - thirteen Google queries cannot end
    sooner than twelve intervals after the first - so it goes whenever it may,
    and every other host fills its gaps instead of queuing after it. Ties fall
    to plan order, because `lanes` keeps insertion order.
    """
    waits = {host: fetcher.ready_in(host) for host in lanes}
    free = [host for host in lanes if waits[host] <= 0]
    if free:
        return max(free, key=lambda host: len(lanes[host]))
    return min(lanes, key=lambda host: waits[host])


def read_sources(fetcher, plan, fetched_at=None):
    """`[(source, keyword_group)]` -> `[(items, error)]`, one per entry, in plan order.

    Sent in whatever order wastes least time on the per-host gap (see
    `_next_host()`), returned in the order planned. The difference must not
    leak: `rank_groups()` sorts stably and `collapse()` keeps the first copy's
    title, so an item list reordered by the transport would change which
    headline ships.
    """
    breaker = _HostBreaker(fetcher)
    lanes = {}
    for index, (source, _) in enumerate(plan):
        host = urlsplit(source.get("url") or "").hostname
        lanes.setdefault(host, []).append(index)

    results = [None] * len(plan)
    while lanes:
        host = _next_host(lanes, breaker)
        index = lanes[host].pop(0)
        if not lanes[host]:
            del lanes[host]
        source, keyword_group = plan[index]
        results[index] = read_source(breaker, source, keyword_group=keyword_group,
                                     fetched_at=fetched_at)
    return results


def collect(results):
    """`[(items, error)]` -> `(items, errors)`, flattened in the same order."""
    items = []
    errors = []
    for got, error in results:
        items.extend(got)
        if error:
            errors.append(error)
    return items, errors


def fixed_plan(cfg):
    """Every enabled `feeds[]` entry as a `read_sources()` plan entry."""
    return [(source, None) for source in cfg.enabled_feeds()]


def read_fixed_feeds(fetcher, cfg, fetched_at=None):
    """Every enabled `feeds[]` entry. Returns (items, errors), in config order."""
    return collect(read_sources(fetcher, fixed_plan(cfg), fetched_at=fetched_at))
