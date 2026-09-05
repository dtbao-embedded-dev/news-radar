#!/usr/bin/env python3
"""Checks for src/news_radar/item.py - plain asserts, no test framework.

    python tests/test_item.py

Standard library only: item.py is a leaf and must stay one, so a test that
needed PyYAML or feedparser to exercise it would be evidence of a layering bug.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar import item as mod  # noqa: E402

FAILURES = []


def check(name, condition, detail=""):
    if not condition:
        FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def eq(name, got, want):
    check(name, got == want, "got {!r}, want {!r}".format(got, want))


# --- strip_html -----------------------------------------------------------

eq("strip_html removes tags",
   mod.strip_html("<b>ESP32</b> ra mat"), "ESP32 ra mat")
eq("strip_html removes an img the way VnExpress ships it",
   mod.strip_html('<img src="x.jpg" alt="a"/>Chip moi cua Espressif'),
   "Chip moi cua Espressif")
eq("strip_html unescapes entities after stripping, not before",
   mod.strip_html("Rust &amp; C"), "Rust & C")
eq("strip_html does not strip text that was escaped markup",
   mod.strip_html("use &lt;stdio.h&gt;"), "use <stdio.h>")
eq("strip_html collapses whitespace and newlines",
   mod.strip_html("  ESP32\n\t  S3  "), "ESP32 S3")
eq("strip_html on empty input", mod.strip_html(""), "")
eq("strip_html on None", mod.strip_html(None), "")


# --- fold -----------------------------------------------------------------

eq("fold lowercases", mod.fold("ESP32"), "esp32")
eq("fold drops Vietnamese diacritics", mod.fold("Điện tử"), "dien tu")
eq("fold handles d-stroke, which NFD does not decompose",
   mod.fold("Đà Nẵng"), "da nang")
eq("fold collapses whitespace", mod.fold("  RISC-V   news "), "risc-v news")
eq("fold keeps punctuation - matching is substring based",
   mod.fold("ESP32-S3"), "esp32-s3")
eq("fold on empty input", mod.fold(""), "")


# --- canonicalise_url -----------------------------------------------------

eq("canonicalise lowercases the host and drops www.",
   mod.canonicalise_url("https://WWW.Example.COM/a"), "https://example.com/a")
eq("canonicalise forces https",
   mod.canonicalise_url("http://example.com/a"), "https://example.com/a")
eq("canonicalise drops every utm_ parameter",
   mod.canonicalise_url("https://example.com/a?utm_source=x&utm_medium=y&id=7"),
   "https://example.com/a?id=7")
eq("canonicalise drops the named tracking parameters",
   mod.canonicalise_url(
       "https://example.com/a?fbclid=1&gclid=2&ref=3&ref_src=4&spm=5&s_cid=6&p=9"),
   "https://example.com/a?p=9")
eq("canonicalise drops the fragment",
   mod.canonicalise_url("https://example.com/a#comments"), "https://example.com/a")
eq("canonicalise strips a trailing slash",
   mod.canonicalise_url("https://example.com/a/b/"), "https://example.com/a/b")
eq("canonicalise keeps a bare root slash",
   mod.canonicalise_url("https://example.com/"), "https://example.com/")
eq("canonicalise keeps a non-tracking query - some sites carry the article id there",
   mod.canonicalise_url("https://vnexpress.net/x.html?p=2"),
   "https://vnexpress.net/x.html?p=2")
eq("canonicalise leaves an already-clean url untouched",
   mod.canonicalise_url("https://lwn.net/Articles/1000/"),
   "https://lwn.net/Articles/1000")
eq("canonicalise preserves path case - only the host is lowercased",
   mod.canonicalise_url("https://Example.com/Articles/Big"),
   "https://example.com/Articles/Big")
eq("canonicalise on empty input", mod.canonicalise_url(""), "")
eq("canonicalise on a non-http scheme returns empty - nothing downstream can use it",
   mod.canonicalise_url("mailto:a@b.c"), "")
eq("canonicalise is idempotent",
   mod.canonicalise_url(mod.canonicalise_url("http://WWW.a.com/x/?utm_source=q#f")),
   "https://a.com/x")


# --- NewsItem and dedup_key ----------------------------------------------

NOW = dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.timezone.utc)


def make(title="ESP32-C6 ships", url="https://example.com/a", **kw):
    return mod.new_item(title=title, url=url, source_id="hn", fetched_at=NOW, **kw)


it = make()
eq("new_item computes canonical_url", it.canonical_url, "https://example.com/a")
eq("new_item falls back to canonical_url for external_id",
   it.external_id, "https://example.com/a")
eq("new_item defaults published_at to None, never to now", it.published_at, None)
eq("new_item defaults keyword_group to None", it.keyword_group, None)
eq("new_item strips html out of the title",
   make(title="<b>ESP32</b>  ships").title, "ESP32 ships")

check("new_item keeps an explicit external_id",
      make(external_id="guid-1").external_id == "guid-1")

same = mod.dedup_key(make(url="http://WWW.example.com/a?utm_source=rss#top"))
eq("the same story from two urls that canonicalise alike shares a dedup key",
   same, mod.dedup_key(it))
check("a different url gives a different dedup key",
      mod.dedup_key(make(url="https://example.com/b")) != same)

nourl = make(url="")
eq("an item with no usable url canonicalises to empty", nourl.canonical_url, "")
check("an item with no url still gets a dedup key", bool(mod.dedup_key(nourl)))
eq("the title fallback ignores case, diacritics and punctuation",
   mod.dedup_key(mod.new_item(title="Điện tử: ESP32!", url="",
                              source_id="genk", fetched_at=NOW)),
   mod.dedup_key(mod.new_item(title="dien tu esp32", url="",
                              source_id="tinhte", fetched_at=NOW)))
check("the title fallback is not the same key as a url key",
      mod.dedup_key(nourl) != same)

# An item without a title is a parse-time drop, not a record with an empty
# headline: every downstream stage displays the title, so there is nothing to
# show and nothing to match on.
try:
    mod.new_item(title="   ", url="https://example.com/a", source_id="hn",
                 fetched_at=NOW)
    FAILURES.append("new_item accepted an empty title")
except ValueError:
    pass


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
