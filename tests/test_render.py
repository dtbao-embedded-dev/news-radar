#!/usr/bin/env python3
"""Checks for src/news_radar/render.py - plain asserts, no test framework.

    python tests/test_render.py

Standard library only. Nothing here reaches the network, and the "page is
self-contained" assertion is exactly that claim tested: a page that pulls a
stylesheet or a script from a CDN stops working the day the homelab is offline,
which is the day someone most wants to read it.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar import render as mod  # noqa: E402

FAILURES = []
TMP = pathlib.Path(tempfile.mkdtemp(prefix="news-radar-render-"))
COUNTER = [0]

VN = dt.timezone(dt.timedelta(hours=7))
NOW = dt.datetime(2026, 9, 5, 2, 0, tzinfo=dt.timezone.utc)  # 09:00 in +07:00
HOUR = dt.timedelta(hours=1)

LABELS = ["ESP32", "Rust", "Security"]
META = {"run_id": "20260905T020000Z", "fetched": 597, "matched": 209,
        "sources": 22, "errors": 1, "generated_at": NOW}


def check(name, condition, detail=""):
    if not condition:
        FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def eq(name, got, want):
    check(name, got == want, "got {!r}, want {!r}".format(got, want))


def data_dir():
    COUNTER[0] += 1
    path = TMP / "out{}".format(COUNTER[0])
    path.mkdir(parents=True)
    return path


def row(title, url, score, sources=("hn",), published_at=NOW - HOUR):
    return {"dedup_key": "k" + title, "title": title, "url": url,
            "canonical_url": url, "score": score, "published_at": published_at,
            "first_seen_at": NOW, "sources": tuple(sources)}


# -- local_tz: never fatal, whatever the host's tz database looks like ------

check("a real zone name yields a tzinfo",
      mod.local_tz("Asia/Ho_Chi_Minh").utcoffset(NOW) is not None)
check("an unknown zone falls back instead of raising",
      mod.local_tz("Definitely/NotAZone").utcoffset(NOW) is not None)
check("an empty zone name falls back too",
      mod.local_tz("").utcoffset(NOW) is not None)


# -- day_bounds: the local day, expressed in UTC ---------------------------

start, end = mod.day_bounds(NOW, VN)
eq("the day starts at local midnight, in UTC",
   start, dt.datetime(2026, 9, 4, 17, 0, tzinfo=dt.timezone.utc))
eq("the day ends 24 hours later",
   end, dt.datetime(2026, 9, 5, 17, 0, tzinfo=dt.timezone.utc))
check("a moment just before local midnight belongs to the previous day",
      mod.day_bounds(dt.datetime(2026, 9, 4, 16, 59, tzinfo=dt.timezone.utc),
                     VN)[0]
      == dt.datetime(2026, 9, 3, 17, 0, tzinfo=dt.timezone.utc))


# -- write: the page itself ------------------------------------------------

root = data_dir()
rows = {
    "ESP32": [row("ESP32-S3 SDK 5.5", "https://example.com/a", 0.91,
                  ("hn", "lobsters")),
              row("ESP32 power rails", "https://example.com/b", 0.72),
              row("ESP32 and <script>alert(1)</script> & friends",
                  "https://example.com/c?x=1&y=2", 0.55),
              row("ESP32 undated", "https://example.com/d", 0.40,
                  published_at=None)],
    "Rust": [row("Rust in the kernel", "https://example.com/r", 0.80)],
}

written = mod.write(root, LABELS, rows, META, VN, threshold=2)
index = root / "index.html"
snapshot = root / "days" / "2026-09-05.html"

eq("write reports both files", sorted(str(p) for p in written),
   sorted([str(index), str(snapshot)]))
check("index.html is written", index.is_file())
check("today's snapshot is written", snapshot.is_file())

html = index.read_text(encoding="utf-8")
eq("the snapshot carries the same body as index.html",
   snapshot.read_text(encoding="utf-8"), html)

# Every group, empty ones included. A keyword that has gone quiet is exactly
# what a total would hide - the log makes the same promise for the same reason.
for label in LABELS:
    check("group {!r} has a section".format(label), label in html)
check("an empty group says so rather than vanishing",
      "Security" in html and html.count("no stories") >= 1)

# The trust boundary: a feed title is somebody else's text.
check("a script tag in a title is escaped, not embedded",
      "<script>alert(1)</script>" not in html)
check("the escaped form is what lands on the page",
      "&lt;script&gt;alert(1)&lt;/script&gt;" in html)
check("an ampersand in a title is escaped", "&amp; friends" in html)
check("an ampersand in a url is escaped too", "x=1&amp;y=2" in html)

# Highlighting: the first `threshold` of each group, or all of them when the
# group is shorter than the threshold.
eq("exactly min(threshold, len(group)) stories are highlighted",
   html.count("story hot"), 2 + 1)

check("the score is on the page", "0.91" in html)
check("the sources that carried a story are on the page",
      "hn" in html and "lobsters" in html)
check("a story with no timestamp renders anyway", "ESP32 undated" in html)
check("the run's own numbers are in the footer",
      "597" in html and "209" in html)

# Self-contained: nothing to fetch. Story links are external by nature; an
# asset is not.
check("no external stylesheet", "<link" not in html.lower()
      or 'rel="stylesheet"' not in html.lower())
check("no external script", 'src="http' not in html)
check("no css @import", "@import" not in html)
check("no external image", "<img" not in html.lower())

# The three page features P3-4 asks for.
check("there is a theme toggle", 'id="theme"' in html)
check("the theme choice is remembered", "localStorage" in html)
check("there is a search box", 'id="q"' in html)
check("the page declares its language and charset",
      "<html lang=" in html and "utf-8" in html.lower())


# -- day history nav -------------------------------------------------------

(root / "days" / "2026-09-03.html").write_text("older", encoding="utf-8")
(root / "days" / "2026-09-04.html").write_text("older", encoding="utf-8")
mod.write(root, LABELS, rows, META, VN, threshold=2)
html = index.read_text(encoding="utf-8")

check("older days are linked", 'days/2026-09-04.html' in html
      and 'days/2026-09-03.html' in html)
eq("newest first",
   html.index("days/2026-09-05.html") < html.index("days/2026-09-04.html")
   < html.index("days/2026-09-03.html"), True)


# -- a day with nothing at all --------------------------------------------

empty_root = data_dir()
mod.write(empty_root, LABELS, {}, META, VN, threshold=5)
html = (empty_root / "index.html").read_text(encoding="utf-8")
check("a day with no matches still renders every group",
      all(label in html for label in LABELS))
eq("and highlights nothing", html.count("story hot"), 0)


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
