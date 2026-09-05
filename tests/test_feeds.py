#!/usr/bin/env python3
"""Checks for src/news_radar/fetch/feeds.py - plain asserts, no test framework.

    python tests/test_feeds.py

Needs feedparser and PyYAML. Every body comes from tests/fixtures/, so nothing
here touches the network: each fixture carries one edge case that
docs/memory-ai/behavior/news-search.md predicted before the code existed.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar import config as cfgmod  # noqa: E402
from news_radar.fetch import feeds as mod  # noqa: E402
from news_radar.fetch.http import HttpError  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
FAILURES = []
UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def check(name, condition, detail=""):
    if not condition:
        FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def eq(name, got, want):
    check(name, got == want, "got {!r}, want {!r}".format(got, want))


def body(name):
    return (FIXTURES / name).read_bytes()


def by_title(items, needle):
    for i in items:
        if needle in i.title:
            return i
    return None


# --- RSS 2.0 --------------------------------------------------------------

lwn = mod.parse(body("rss_lwn.xml"), "rss", "lwn", fetched_at=NOW)

eq("an item with an empty title is dropped at parse time", len(lwn), 3)
eq("every item is tagged with its source id",
   sorted({i.source_id for i in lwn}), ["lwn"])
eq("fetched_at is the run's timestamp, not per item",
   sorted({i.fetched_at for i in lwn}), [NOW])

paywalled = by_title(lwn, "subscriber-only")
check("the LWN [$] prefix survives, so a ! filter can still exclude it",
      paywalled is not None and paywalled.title.startswith("[$]"),
      repr(paywalled.title if paywalled else None))

eq("an RFC 822 pubDate in UTC is parsed",
   paywalled.published_at, dt.datetime(2026, 9, 4, 9, 30, tzinfo=UTC))

offset = by_title(lwn, "Kernel 7.1")
eq("a pubDate with an offset is converted to UTC, not truncated",
   offset.published_at, dt.datetime(2026, 9, 4, 4, 0, tzinfo=UTC))
eq("an entity in the title is decoded", offset.title,
   "Kernel 7.1 released — what changed")
eq("guid becomes external_id when the feed gives one",
   offset.external_id, "lwn-1000002")
eq("the item url is kept as published",
   offset.url,
   "https://lwn.net/Articles/1000002/?utm_source=rss&utm_medium=feed")
eq("canonical_url drops the tracking parameters and the trailing slash",
   offset.canonical_url, "https://lwn.net/Articles/1000002")

undated = by_title(lwn, "no pubDate")
eq("a missing pubDate is None, never now", undated.published_at, None)
eq("with no guid, external_id falls back to the canonical url",
   undated.external_id, "https://lwn.net/Articles/1000003")

vn = mod.parse(body("rss_vnexpress.xml"), "rss", "vnexpress_sohoa", fetched_at=NOW)
eq("one VnExpress item", len(vn), 1)
eq("markup and runs of whitespace are stripped out of the title, once, here",
   vn[0].title, "Chip ESP32-C6 ra mắt tại Việt Nam")
check("the description, img tag and all, never reaches the item",
      "img" not in vn[0].title and "vnecdn" not in vn[0].title)


# --- Atom -----------------------------------------------------------------

reddit = mod.parse(body("atom_reddit.xml"), "atom", "r_embedded", fetched_at=NOW)
eq("both Atom entries parsed", len(reddit), 2)

rtos = by_title(reddit, "Best RTOS")
eq("the rel=alternate href is the url",
   rtos.url, "https://www.reddit.com/r/embedded/comments/abc123/best_rtos/")
eq("the Atom entry id becomes external_id", rtos.external_id, "t3_abc123")
eq("published wins over updated when both are there",
   rtos.published_at, dt.datetime(2026, 9, 4, 10, 0, tzinfo=UTC))

zephyr = by_title(reddit, "Zephyr")
eq("updated is used when there is no published",
   zephyr.published_at, dt.datetime(2026, 9, 4, 11, 0, tzinfo=UTC))


# --- HN Algolia JSON ------------------------------------------------------

hn = mod.parse(body("hn_algolia.json"), "hn_algolia_json", "hn_algolia",
               keyword_group="ESP32", fetched_at=NOW)

eq("the untitled hit is dropped, the other two survive", len(hn), 2)
eq("a search item carries the group whose term produced the query",
   sorted({i.keyword_group for i in hn}), ["ESP32"])

zep = by_title(hn, "mainline Zephyr")
eq("the hit url is used when there is one",
   zep.url, "https://zephyrproject.org/esp32-c6/")
eq("objectID becomes external_id", zep.external_id, "41000001")
eq("created_at is parsed as UTC",
   zep.published_at, dt.datetime(2026, 9, 4, 8, 0, tzinfo=UTC))

ask = by_title(hn, "Ask HN")
# An Ask HN post has no outbound url. Publishing it with no link at all would
# be a report entry nobody can open.
eq("a null url falls back to the HN item permalink",
   ask.url, "https://news.ycombinator.com/item?id=41000002")
eq("and that permalink canonicalises to something usable",
   ask.canonical_url, "https://news.ycombinator.com/item?id=41000002")


# --- the bodies that are not feeds ---------------------------------------

eq("a malformed feed yields no items rather than raising",
   mod.parse(body("broken.xml"), "rss", "hn", fetched_at=NOW), [])
eq("an empty body yields no items", mod.parse(b"", "rss", "hn", fetched_at=NOW), [])
eq("html served instead of a feed yields no items",
   mod.parse(b"<html><body>404</body></html>", "rss", "hn", fetched_at=NOW), [])
eq("json that is not the Algolia shape yields no items",
   mod.parse(b'{"error": "nope"}', "hn_algolia_json", "hn_algolia", fetched_at=NOW),
   [])
eq("json that is not json at all yields no items",
   mod.parse(b"<rss/>", "hn_algolia_json", "hn_algolia", fetched_at=NOW), [])

try:
    mod.parse(b"x", "csv", "hn", fetched_at=NOW)
    FAILURES.append("an unknown format was accepted")
except ValueError:
    pass


# --- failure isolation ----------------------------------------------------

class FakeFetcher:
    """Answers from the fixtures; raises for the sources told to fail."""

    def __init__(self, bodies, failing=()):
        self.bodies = bodies
        self.failing = set(failing)
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if url in self.failing:
            raise HttpError("HTTP 403 Blocked", status=403, url=url)
        return self.bodies[url]


OK_URL = "https://lwn.net/headlines/rss"
BAD_URL = "https://www.reddit.com/r/embedded/.rss"
EMPTY_URL = "https://news.google.com/rss/search?q=x"

fetcher = FakeFetcher({OK_URL: body("rss_lwn.xml"),
                       EMPTY_URL: body("broken.xml")},
                      failing=[BAD_URL])

items, error = mod.read_source(fetcher, {"id": "lwn", "url": OK_URL}, fetched_at=NOW)
eq("a healthy source returns its items and no error", (len(items), error), (3, None))

items, error = mod.read_source(fetcher, {"id": "r_embedded", "url": BAD_URL},
                               fetched_at=NOW)
eq("a failing source returns no items", items, [])
check("a failing source returns one error naming it and why",
      error is not None and error[0] == "r_embedded" and "403" in error[1],
      repr(error))

items, error = mod.read_source(fetcher, {"id": "google_news", "url": EMPTY_URL},
                               fetched_at=NOW)
# Google News answers a throttled query with an empty feed rather than an
# error. That is worth a log line, but calling it a failure would put a red
# entry in the run for a source that is merely quiet.
eq("an empty parse is a soft failure: no items, no error", (items, error), ([], None))

cfg = cfgmod.Config({"feeds": [
    {"id": "lwn", "url": OK_URL, "enabled": True},
    {"id": "r_embedded", "url": BAD_URL, "enabled": True},
    {"id": "hn", "url": "https://hnrss.org/frontpage", "enabled": False},
]})
fetcher2 = FakeFetcher({OK_URL: body("rss_lwn.xml")}, failing=[BAD_URL])
all_items, errors = mod.read_fixed_feeds(fetcher2, cfg, fetched_at=NOW)

eq("one dead source does not stop the others", len(all_items), 3)
eq("and it is reported exactly once", len(errors), 1)
eq("a disabled feed is not fetched at all", len(fetcher2.calls), 2)
eq("the items are tagged with the source they came from",
   sorted({i.source_id for i in all_items}), ["lwn"])
check("a fixed-feed item has no keyword group",
      all(i.keyword_group is None for i in all_items))


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
