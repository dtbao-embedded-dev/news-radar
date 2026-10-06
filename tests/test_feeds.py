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
check("the description never reaches the title",
      "img" not in vn[0].title and "vnecdn" not in vn[0].title)
# It reaches the excerpt instead - which is where the AI summary is written
# from, and the reason it is stripped rather than dropped.
eq("the description becomes the excerpt, tags stripped",
   vn[0].excerpt, "Espressif cong bo")
check("...and the img markup does not survive into it",
      "vnecdn" not in vn[0].excerpt and "<" not in vn[0].excerpt, vn[0].excerpt)


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


# --- read_sources: the order requests go out in ---------------------------

class ClockFetcher:
    """A Fetcher on a fake clock: the per-host gap is real, the time is not.

    `get()` waits out the host's interval the way `Fetcher._throttle()` does,
    then spends `latency` on the answer, all by moving `now` - so a schedule's
    wall time can be read off exactly instead of measured with a stopwatch.
    """

    def __init__(self, interval, latency, failing=None, bodies=None):
        self.interval = interval
        self.latency = latency
        self.failing = dict(failing or {})  # url -> HttpError to raise
        self.bodies = bodies or {}
        self.now = 0.0
        self.last = {}
        self.calls = []

    def ready_in(self, host):
        last = self.last.get(host)
        return 0.0 if last is None else max(0.0, self.interval - (self.now - last))

    def get(self, url):
        host = url.split("/")[2]
        self.now += self.ready_in(host)
        self.last[host] = self.now
        self.calls.append(url)
        self.now += self.latency
        if url in self.failing:
            raise self.failing[url]
        return self.bodies.get(url, b"")


def plan(*urls):
    return [({"id": "s{}".format(i), "url": u}, None) for i, u in enumerate(urls)]


def host(url):
    return url.split("/")[2]


GOOGLE_Q = ["https://news.google.com/rss/search?q={}".format(i) for i in range(4)]
FIXED = ["https://hnrss.org/frontpage", "https://lobste.rs/rss",
         "https://lwn.net/headlines/rss"]

# The busiest host is the critical path: four Google queries cannot finish in
# less than three intervals, whatever else happens. Everything else belongs in
# the gaps between them, not queued after them.
clock = ClockFetcher(interval=1.0, latency=0.1)
results = mod.read_sources(clock, plan(*(FIXED + GOOGLE_Q)), fetched_at=NOW)
eq("the busiest host goes first, and the fixed feeds fill its gaps",
   [host(u) for u in clock.calls],
   ["news.google.com", "hnrss.org", "lobste.rs", "lwn.net",
    "news.google.com", "news.google.com", "news.google.com"])
check("so the run takes the critical path and no longer",
      abs(clock.now - 3.1) < 1e-9, repr(clock.now))
eq("one result per planned source, in plan order",
   len(results), len(FIXED + GOOGLE_Q))

# The same plan sent in plan order would wait out every Google gap in full.
naive = ClockFetcher(interval=1.0, latency=0.1)
for u in FIXED + GOOGLE_Q:
    naive.get(u)
check("which is faster than sending the plan as written",
      clock.now < naive.now, "{} vs {}".format(clock.now, naive.now))

# A fetcher without ready_in() - the test doubles elsewhere - is treated as
# always ready, and the busiest-host-first rule alone still interleaves.
plain = FakeFetcher({u: b"" for u in GOOGLE_Q[:2] + FIXED[:2]})
mod.read_sources(plain, plan(*(GOOGLE_Q[:2] + FIXED[:2])), fetched_at=NOW)
eq("no clock: busiest host first, then plan order",
   [host(u) for u in plain.calls],
   ["news.google.com", "news.google.com", "hnrss.org", "lobste.rs"])

clock_items = ClockFetcher(interval=1.0, latency=0.1,
                           bodies={FIXED[2]: body("rss_lwn.xml"),
                                   GOOGLE_Q[0]: body("rss_vnexpress.xml")})
results = mod.read_sources(clock_items, [({"id": "lwn", "url": FIXED[2]}, None),
                                         ({"id": "gn", "url": GOOGLE_Q[0]}, "ESP32")],
                           fetched_at=NOW)
eq("results come back in plan order, not fetch order",
   [{i.source_id for i in got} for got, _ in results], [{"lwn"}, {"gn"}])
eq("and each carries its own keyword group",
   [{i.keyword_group for i in got} for got, _ in results], [{None}, {"ESP32"}])


# --- read_sources: a host that is down is asked once ----------------------

# Google answering 429 is the case this exists for: every later query to it
# would retry and wait too, up to RETRY_AFTER_MAX each, and the cycle would
# stall past its own interval for results that are not coming.
throttled = HttpError("HTTP 429 Too Many Requests", status=429, url=GOOGLE_Q[0])
down = ClockFetcher(interval=1.0, latency=0.1,
                    failing={u: throttled for u in GOOGLE_Q})
results = mod.read_sources(down, plan(*(GOOGLE_Q + FIXED)), fetched_at=NOW)
eq("after HOST_STRIKES failures in a row the host is not asked again",
   [u for u in down.calls if host(u) == "news.google.com"],
   GOOGLE_Q[:mod.HOST_STRIKES])
eq("every other host is still asked",
   sorted(u for u in down.calls if host(u) != "news.google.com"), sorted(FIXED))
errors = [error for _, error in results if error]
eq("but every skipped source is still its own error, so a dead host is visible",
   [e[0] for e in errors], ["s0", "s1", "s2", "s3"])
check("and the skip says which failure it is standing in for",
      "429" in errors[3][1] and "news.google.com" in errors[3][1]
      and "skipped" in errors[3][1], repr(errors[3]))

# One 429 can be a blip, and search.py's contract is that one throttled query
# must not cost the other groups their results.
blip = ClockFetcher(interval=1.0, latency=0.1, failing={GOOGLE_Q[0]: throttled})
mod.read_sources(blip, plan(*GOOGLE_Q), fetched_at=NOW)
eq("a single failure leaves the host in the plan", blip.calls, GOOGLE_Q)

# The strikes must be consecutive: an answer in between is the host working.
flaky = ClockFetcher(interval=1.0, latency=0.1,
                     failing={GOOGLE_Q[0]: throttled, GOOGLE_Q[2]: throttled})
mod.read_sources(flaky, plan(*GOOGLE_Q), fetched_at=NOW)
eq("failures separated by a success never add up", flaky.calls, GOOGLE_Q)

# A network failure is the same class - DNS gone, connection refused, timeout -
# and the fetcher reports it with no status.
dns = HttpError("URLError: Name or service not known", url=GOOGLE_Q[0])
gone = ClockFetcher(interval=1.0, latency=0.1, failing={u: dns for u in GOOGLE_Q})
mod.read_sources(gone, plan(*GOOGLE_Q), fetched_at=NOW)
eq("a network failure takes the host out too",
   gone.calls, GOOGLE_Q[:mod.HOST_STRIKES])

# A 403 or a 404 is a verdict on one url, not on the host: Reddit refuses one
# path and serves the next, and GitHub 404s a renamed repo and nothing else.
refused = HttpError("HTTP 404 Not Found", status=404, url=GOOGLE_Q[0])
picky = ClockFetcher(interval=1.0, latency=0.1,
                     failing={u: refused for u in GOOGLE_Q})
mod.read_sources(picky, plan(*GOOGLE_Q), fetched_at=NOW)
eq("a non-retryable status never takes the host out", picky.calls, GOOGLE_Q)


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
