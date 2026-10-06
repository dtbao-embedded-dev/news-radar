#!/usr/bin/env python3
"""Checks for src/news_radar/fetch/search.py - plain asserts, no test framework.

    python tests/test_search.py

Needs feedparser and PyYAML. The URL building is pure and is checked exactly,
character for character: a template that reaches the engine slightly wrong
returns plausible-looking results for the wrong query, which is the kind of bug
that survives a whole release.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar import config as cfgmod  # noqa: E402
from news_radar import keywords as kwmod  # noqa: E402
from news_radar.fetch import search as mod  # noqa: E402
from news_radar.fetch.http import HttpError  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
FAILURES = []
NOW = dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.timezone.utc)

GOOGLE = {"id": "google_news", "format": "rss", "enabled": True,
          "url": "https://news.google.com/rss/search?q={kw}&hl=vi&gl=VN&ceid=VN:vi"}
ALGOLIA = {"id": "hn_algolia", "format": "hn_algolia_json", "enabled": True,
           "url": "https://hn.algolia.com/api/v1/search?query={kw}"}
REDDIT = {"id": "reddit_search", "format": "atom", "enabled": False,
          "url": "https://www.reddit.com/search.rss?q={kw}&sort=new"}


def check(name, condition, detail=""):
    if not condition:
        FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def eq(name, got, want):
    check(name, got == want, "got {!r}, want {!r}".format(got, want))


def group(primary, label=None, extra=()):
    g = kwmod.KeywordGroup(primary=primary, label=label or primary)
    g.terms = [primary] + list(extra)
    return g


# --- build_urls: pure, and exact -----------------------------------------

built = mod.build_urls([group("ESP32")], [GOOGLE, ALGOLIA])

eq("one group times two templates is two urls", len(built), 2)
eq("a single-word term needs no quoting",
   built[0][0],
   "https://news.google.com/rss/search?q=ESP32&hl=vi&gl=VN&ceid=VN:vi")
eq("the locale parameters survive untouched - only {kw} is replaced",
   built[0][0].endswith("&hl=vi&gl=VN&ceid=VN:vi"), True)
eq("the second template gets the same term",
   built[1][0], "https://hn.algolia.com/api/v1/search?query=ESP32")

eq("each url carries the template that produced it",
   [t["id"] for _, t, _ in built], ["google_news", "hn_algolia"])
eq("and the group whose term it is",
   [g.primary for _, _, g in built], ["ESP32", "ESP32"])

# A multi-word term unquoted is three separate words to a search engine, and
# "embedded linux" comes back as everything about Linux.
eq("a multi-word term is quoted as a phrase, then encoded",
   mod.build_urls([group("embedded linux")], [GOOGLE])[0][0],
   "https://news.google.com/rss/search?"
   "q=%22embedded+linux%22&hl=vi&gl=VN&ceid=VN:vi")
eq("the phrase quoting applies to every template",
   mod.build_urls([group("Rust embedded")], [ALGOLIA])[0][0],
   "https://hn.algolia.com/api/v1/search?query=%22Rust+embedded%22")

eq("a hyphenated single word is not quoted and not escaped",
   mod.build_urls([group("RISC-V")], [ALGOLIA])[0][0],
   "https://hn.algolia.com/api/v1/search?query=RISC-V")
eq("a term with url-significant characters is escaped",
   mod.build_urls([group("C++ & rust")], [ALGOLIA])[0][0],
   "https://hn.algolia.com/api/v1/search?query=%22C%2B%2B+%26+rust%22")
eq("a term with diacritics is escaped as utf-8",
   mod.build_urls([group("điện tử")], [ALGOLIA])[0][0],
   "https://hn.algolia.com/api/v1/search?"
   "query=%22%C4%91i%E1%BB%87n+t%E1%BB%AD%22")

eq("only the primary term is queried - later terms cost no request",
   len(mod.build_urls([group("ESP32", extra=["ESP-IDF", "ESP32-S3"])], [GOOGLE])),
   1)

eq("the cost is len(groups) x len(templates), stated out loud",
   len(mod.build_urls([group("ESP32"), group("RTOS"), group("CVE")],
                      [GOOGLE, ALGOLIA])),
   6)

eq("no group means no request", mod.build_urls([], [GOOGLE, ALGOLIA]), [])
eq("no template means no request", mod.build_urls([group("ESP32")], []), [])

# A template whose url lost its {kw} would query the same thing for every
# group - config.validate() rejects it, and this is the second line of defence.
eq("a template with no {kw} contributes nothing",
   mod.build_urls([group("ESP32")],
                  [{"id": "broken", "url": "https://x.test/search"}]),
   [])


# --- read_search_feeds ----------------------------------------------------

class FakeFetcher:
    def __init__(self, bodies, failing=()):
        self.bodies = bodies
        self.failing = set(failing)
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if url in self.failing:
            raise HttpError("HTTP 429 Too Many Requests", status=429, url=url)
        return self.bodies.get(url, b"")


ALGOLIA_URL = "https://hn.algolia.com/api/v1/search?query=ESP32"
GOOGLE_URL = ("https://news.google.com/rss/search?"
              "q=ESP32&hl=vi&gl=VN&ceid=VN:vi")

cfg = cfgmod.Config({"search_templates": [GOOGLE, ALGOLIA, REDDIT]})
groups = [group("ESP32", label="ESP32 news")]

fetcher = FakeFetcher(
    {ALGOLIA_URL: (FIXTURES / "hn_algolia.json").read_bytes()},
    failing=[GOOGLE_URL])
items, errors = mod.read_search_feeds(fetcher, cfg, groups, fetched_at=NOW)

eq("a disabled template is never queried", len(fetcher.calls), 2)
check("and it is not among the ones that were",
      all("reddit" not in u for u in fetcher.calls), repr(fetcher.calls))

eq("the items come from the template that answered", len(items), 2)
eq("a search item is tagged with the template id, not the feed id",
   sorted({i.source_id for i in items}), ["hn_algolia"])
eq("and with the group whose term produced the query",
   sorted({i.keyword_group for i in items}), ["ESP32 news"])

eq("the throttled template is reported once", len(errors), 1)
check("the error names the template and the reason",
      errors[0][0] == "google_news" and "429" in errors[0][1], repr(errors))

# One group failing on one template must not cost the other groups their
# results: 20 keyword groups behind a single 429 is the whole run.
many = [group("ESP32"), group("RTOS")]
fetcher2 = FakeFetcher(
    {"https://hn.algolia.com/api/v1/search?query=RTOS":
     (FIXTURES / "hn_algolia.json").read_bytes()},
    failing=["https://hn.algolia.com/api/v1/search?query=ESP32"])
items2, errors2 = mod.read_search_feeds(
    fetcher2, cfgmod.Config({"search_templates": [ALGOLIA]}), many, fetched_at=NOW)
eq("the second group still gets its items", len(items2), 2)
eq("and the first group's failure is its own error", len(errors2), 1)


# --- fetch order: interleaved by host, results in plan order --------------

class ClockFetcher(FakeFetcher):
    """FakeFetcher with a fake clock behind a per-host gap of 1.0 s."""

    def __init__(self, bodies=None, failing=()):
        super().__init__(bodies or {}, failing)
        self.now = 0.0
        self.last = {}

    def ready_in(self, host_name):
        last = self.last.get(host_name)
        return 0.0 if last is None else max(0.0, 1.0 - (self.now - last))

    def get(self, url):
        self.now += self.ready_in(url.split("/")[2])
        self.last[url.split("/")[2]] = self.now
        self.now += 0.1
        return super().get(url)


def host(url):
    return url.split("/")[2]


# Template-major, every request after the first queues a full interval behind
# the one before it on the same host. Interleaved, each host's gap is spent
# waiting on the other host's answer instead.
three = [group("ESP32"), group("RTOS"), group("CVE")]
fetcher3 = FakeFetcher({})
mod.read_search_feeds(fetcher3, cfgmod.Config({"search_templates": [GOOGLE, ALGOLIA]}),
                      three, fetched_at=NOW)
eq("two hosts alternate request by request",
   [host(u) for u in fetcher3.calls],
   ["news.google.com", "hn.algolia.com"] * 3)

# Two templates on one host are one lane: the throttle is per hostname, so
# alternating between them would gain nothing and is not attempted.
GOOGLE_EN = dict(GOOGLE, id="google_news_en",
                 url="https://news.google.com/rss/search?q={kw}&hl=en")
fetcher4 = ClockFetcher()
mod.read_search_feeds(
    fetcher4, cfgmod.Config({"search_templates": [GOOGLE, GOOGLE_EN, ALGOLIA]}),
    [group("ESP32"), group("RTOS")], fetched_at=NOW)
eq("a shared host is one lane, and the other host still interleaves with it",
   [host(u) for u in fetcher4.calls],
   ["news.google.com", "hn.algolia.com", "news.google.com", "hn.algolia.com",
    "news.google.com", "news.google.com"])
eq("and every planned url is still fetched exactly once",
   sorted(fetcher4.calls),
   sorted(u for u, _, _ in mod.build_urls([group("ESP32"), group("RTOS")],
                                          [GOOGLE, GOOGLE_EN, ALGOLIA])))

# The fetch order is a transport detail. What comes back must not depend on
# it: rank sorts stably and collapse keeps the first copy's title, so a
# reordered item list would change which headline ships.
ALGOLIA_RTOS = "https://hn.algolia.com/api/v1/search?query=RTOS"
GOOGLE_RTOS = "https://news.google.com/rss/search?q=RTOS&hl=vi&gl=VN&ceid=VN:vi"
algolia_body = (FIXTURES / "hn_algolia.json").read_bytes()
fetcher5 = FakeFetcher({ALGOLIA_URL: algolia_body, ALGOLIA_RTOS: algolia_body,
                        GOOGLE_URL: (FIXTURES / "rss_lwn.xml").read_bytes()},
                       failing=[GOOGLE_RTOS])
items5, errors5 = mod.read_search_feeds(
    fetcher5, cfgmod.Config({"search_templates": [GOOGLE, ALGOLIA]}),
    [group("ESP32"), group("RTOS")], fetched_at=NOW)
eq("items come back template-major, as planned, not as fetched",
   [(i.source_id, i.keyword_group) for i in items5],
   [("google_news", "ESP32")] * (len(items5) - 4)
   + [("hn_algolia", "ESP32")] * 2 + [("hn_algolia", "RTOS")] * 2)
check("the google template answered at all", len(items5) > 4, repr(len(items5)))
eq("and the failure is still reported", [e[0] for e in errors5], ["google_news"])


# --- read_all_sources: fixed feeds and searches on one schedule ------------

LWN = "https://lwn.net/headlines/rss"
both_cfg = cfgmod.Config({
    "feeds": [{"id": "lwn", "url": LWN, "enabled": True}],
    "search_templates": [GOOGLE]})
fetcher6 = ClockFetcher({LWN: (FIXTURES / "rss_lwn.xml").read_bytes(),
                         GOOGLE_URL: (FIXTURES / "rss_vnexpress.xml").read_bytes()})
(feed6, feed_err6), (search6, search_err6) = mod.read_all_sources(
    fetcher6, both_cfg, [group("ESP32"), group("RTOS")], fetched_at=NOW)
eq("the fixed feed is sent inside the search host's gap, not before it",
   [host(u) for u in fetcher6.calls],
   ["news.google.com", "lwn.net", "news.google.com"])
eq("the fixed half comes back as the fixed half",
   ({i.source_id for i in feed6}, feed_err6), ({"lwn"}, []))
check("and the search half as the search half",
      bool(search6) and {i.source_id for i in search6} == {"google_news"}
      and search_err6 == [], repr((len(search6), search_err6)))


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
