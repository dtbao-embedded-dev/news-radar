#!/usr/bin/env python3
"""Checks for src/news_radar/rank.py - plain asserts, no test framework.

    python tests/test_rank.py

Standard library only. The clock is passed in, never read: every freshness
assertion here is exact because `now` is a fixed timestamp, not `utcnow()`.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar import keywords  # noqa: E402
from news_radar import rank as mod  # noqa: E402
from news_radar.item import new_item  # noqa: E402

FAILURES = []
TMP = pathlib.Path(tempfile.mkdtemp(prefix="news-radar-rank-"))
COUNTER = [0]

NOW = dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.timezone.utc)
HOUR = dt.timedelta(hours=1)

WEIGHTS = {
    "weight_source": 0.5,
    "weight_frequency": 0.3,
    "weight_freshness": 0.2,
    "freshness_half_life_hours": 12.0,
}
SOURCE_WEIGHTS = {"hn": 1.0, "lobsters": 0.9, "genk": 0.6, "tinhte": 0.6, "lwn": 0.9}


def check(name, condition, detail=""):
    if not condition:
        FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def eq(name, got, want):
    check(name, got == want, "got {!r}, want {!r}".format(got, want))


def close(name, got, want):
    check(name, abs(got - want) < 1e-9, "got {!r}, want {!r}".format(got, want))


def parse(text):
    COUNTER[0] += 1
    path = TMP / "kw{}.txt".format(COUNTER[0])
    path.write_text(text, encoding="utf-8")
    return keywords.parse(path)[0]


def item(title, url, source_id, published_at=None):
    return new_item(title, url, source_id, NOW, published_at=published_at)


def story(source_ids, published_at=None, labels=("ESP32",), title="A story"):
    return mod.Story(
        item=item(title, "https://example.com/" + title.replace(" ", "-"),
                  source_ids[0], published_at),
        source_ids=tuple(source_ids),
        labels=tuple(labels),
        published_at=published_at,
    )


def score(st):
    return mod.score(st, WEIGHTS, SOURCE_WEIGHTS, NOW)


# --- collapse -------------------------------------------------------------

URL = "https://lwn.net/Articles/1000001/"
pairs = [
    (item("Zephyr 4.2 released", URL, "lwn", NOW - 5 * HOUR), ["RTOS"]),
    (item("Zephyr 4.2 released", URL + "?utm_source=x", "hn", NOW - 8 * HOUR),
     ["RTOS", "ESP32"]),
    (item("Something else", "https://lobste.rs/s/abc", "lobsters", NOW - HOUR),
     ["ESP32"]),
]
collapsed = mod.collapse(pairs)

eq("two spellings of one URL collapse into one story", len(collapsed), 2)
eq("a different story stays its own row", collapsed[1].item.title, "Something else")
eq("the survivor unions its sources", collapsed[0].source_ids, ("lwn", "hn"))
eq("the survivor unions its labels", collapsed[0].labels, ("RTOS", "ESP32"))
eq("the survivor keeps the earliest published_at",
   collapsed[0].published_at, NOW - 8 * HOUR)
eq("the first-seen item is the one kept for display",
   collapsed[0].item.source_id, "lwn")

undated = mod.collapse([
    (item("No date here", "https://example.com/x", "genk"), ["ESP32"]),
    (item("No date here", "https://example.com/x", "hn", NOW - 3 * HOUR), ["ESP32"]),
])
eq("a known timestamp beats an unknown one", undated[0].published_at, NOW - 3 * HOUR)
eq("two items with no date at all leave it unknown",
   mod.collapse([
       (item("Dateless", "https://example.com/y", "genk"), ["ESP32"]),
       (item("Dateless", "https://example.com/y", "hn"), ["ESP32"]),
   ])[0].published_at, None)
eq("the same source twice is counted once",
   mod.collapse([
       (item("Twice", "https://example.com/z", "hn"), ["ESP32"]),
       (item("Twice", "https://example.com/z", "hn"), ["ESP32"]),
   ])[0].source_ids, ("hn",))
eq("nothing in, nothing out", mod.collapse([]), [])


# --- score ----------------------------------------------------------------

# 0.5 * max(1.0) + 0.3 * min(1, 1/3) + 0.2 * 0.5 ** (12/12) = 0.5 + 0.1 + 0.1
close("the score is the documented weighted sum",
      score(story(["hn", "lobsters"], NOW - 12 * HOUR)), 0.7)

close("an unknown published_at gives a freshness term of exactly zero",
      score(story(["hn"])), 0.5)
close("a story published right now gets the full freshness term",
      score(story(["hn"], NOW)), 0.7)
close("a future timestamp scores no higher than one published now",
      score(story(["hn"], NOW + 6 * HOUR)), score(story(["hn"], NOW)))
close("the source term takes the best of its sources, not the first",
      score(story(["genk", "hn"])), 0.5 + 0.3 * (1 / 3))
close("an unknown source id falls back to weight 1.0",
      score(story(["mystery"])), 0.5)

four = score(story(["hn", "lobsters", "genk", "tinhte"]))
five = score(story(["hn", "lobsters", "genk", "tinhte", "lwn"]))
close("four sources saturate the frequency term", four, 0.5 + 0.3)
close("a fifth source adds nothing", five, four)

close("the weights are read from the mapping, not hardcoded",
      mod.score(story(["hn"], NOW),
                {"weight_source": 1.0, "weight_frequency": 0.0,
                 "weight_freshness": 0.0, "freshness_half_life_hours": 12.0},
                SOURCE_WEIGHTS, NOW),
      1.0)


# --- rank_groups: order and caps ------------------------------------------

GROUPS = parse("""\
ESP32
@2
=> ESP32

firmware
=> Firmware

RISC-V
=> RISC-V
""")

stories = [
    story(["genk"], NOW - 48 * HOUR, ("ESP32",), "third"),
    story(["hn", "lobsters", "genk", "tinhte"], NOW, ("ESP32", "Firmware"), "first"),
    story(["lwn"], NOW - 2 * HOUR, ("ESP32", "Firmware"), "second"),
]
ranked = mod.rank_groups(stories, GROUPS, WEIGHTS, SOURCE_WEIGHTS, NOW,
                         default_cap=0)

eq("every group gets a section, empty ones included",
   sorted(ranked), ["ESP32", "Firmware", "RISC-V"])
eq("a group nothing matched is empty rather than absent", ranked["RISC-V"], [])
eq("the group's own @n cap wins", len(ranked["ESP32"]), 2)
eq("the highest score comes first",
   [s.item.title for s in ranked["ESP32"]], ["first", "second"])
eq("a group with no @n and no default cap keeps everything",
   [s.item.title for s in ranked["Firmware"]], ["first", "second"])
check("the score is written back onto the story", stories[1].score > stories[0].score)

capped = mod.rank_groups(stories, GROUPS, WEIGHTS, SOURCE_WEIGHTS, NOW,
                         default_cap=1)
eq("report.max_per_group caps a group that has no @n of its own",
   len(capped["Firmware"]), 1)
eq("a group's own @n still wins over the fallback", len(capped["ESP32"]), 2)

zero = parse("ESP32\n@0\n=> ESP32\n")
eq("an explicit @0 means unlimited, like the config default",
   len(mod.rank_groups(stories, zero, WEIGHTS, SOURCE_WEIGHTS, NOW,
                       default_cap=1)["ESP32"]), 3)


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
