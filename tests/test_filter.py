#!/usr/bin/env python3
"""Checks for src/news_radar/filter.py - plain asserts, no test framework.

    python tests/test_filter.py

Standard library only. Keyword groups come from real files written to a temp
directory and parsed by `keywords.parse()`, not from hand-built objects: the
match engine has to work on what the shipped file syntax actually produces.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar import filter as mod  # noqa: E402
from news_radar import keywords  # noqa: E402
from news_radar.item import new_item  # noqa: E402

FAILURES = []
TMP = pathlib.Path(tempfile.mkdtemp(prefix="news-radar-filter-"))
COUNTER = [0]
NOW = dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.timezone.utc)


def check(name, condition, detail=""):
    if not condition:
        FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def eq(name, got, want):
    check(name, got == want, "got {!r}, want {!r}".format(got, want))


def parse(text):
    COUNTER[0] += 1
    path = TMP / "kw{}.txt".format(COUNTER[0])
    path.write_text(text, encoding="utf-8")
    return keywords.parse(path)


def item(title, url=None, source_id="hn"):
    return new_item(title, url or "https://example.com/" + str(abs(hash(title))),
                    source_id, NOW)


# --- the global filter runs before any group ------------------------------

GROUPS, GLOBAL = parse("""\
ESP32
@10
=> ESP32

[GLOBAL_FILTER]
!giveaway
!khuyen mai
""")

check("a global term blocks the item",
      mod.blocked(item("Win an ESP32 giveaway"), GLOBAL))
check("an item with no global term is not blocked",
      not mod.blocked(item("ESP32-S3 released"), GLOBAL))
check("the global filter folds diacritics too",
      mod.blocked(item("ESP32 khuyến mãi tháng 9"), GLOBAL))
check("an empty global filter blocks nothing",
      not mod.blocked(item("Win an ESP32 giveaway"), []))

eq("a blocked item never reaches a group it would have matched",
   mod.select([item("Win an ESP32 giveaway")], GROUPS, GLOBAL), [])
eq("the same item passes when the global filter is empty",
   [labels for _, labels in mod.select([item("Win an ESP32 giveaway")], GROUPS, [])],
   [["ESP32"]])


# --- folding: case and Vietnamese diacritics ------------------------------

VN, _ = parse("""\
dien tu
=> Điện tử
""")

check("a keyword typed without diacritics matches a title with them",
      mod.group_matches(item("Điện tử công nghiệp Việt Nam"), VN[0]))
check("a keyword matches regardless of case",
      mod.group_matches(item("ĐIỆN TỬ 2026"), VN[0]))
check("an unrelated title does not match",
      not mod.group_matches(item("Rust 1.90 released"), VN[0]))

PUNCT, _ = parse("""\
ESP32-S3
=> ESP32-S3
""")

check("punctuation survives folding, so a hyphenated part number still matches",
      mod.group_matches(item("New ESP32-S3 devkit"), PUNCT[0]))


# --- a /regex/ runs against the original title, not the folded one --------

RX, _ = parse("""\
zzz-no-such-term
/CVE-\\d{4}-\\d+/
=> Security
""")

check("the regex matches the original title",
      mod.group_matches(item("CVE-2026-1234 in the ESP-IDF TLS stack"), RX[0]))
check("the same title lowercased does not match - the regex saw the original",
      not mod.group_matches(item("cve-2026-1234 in the esp-idf tls stack"), RX[0]))
check("a title matching neither the term nor the regex does not match",
      not mod.group_matches(item("Zephyr 4.0 released"), RX[0]))


# --- + required, ! excluded ----------------------------------------------

REQ, _ = parse("""\
ESP32
+firmware
=> Firmware

ESP32
!hiring
=> ESP32
""")
required_group, excluding_group = REQ

check("a required term that is absent blocks the match",
      not mod.group_matches(item("ESP32 news roundup"), required_group))
check("a required term that is present allows it",
      mod.group_matches(item("ESP32 firmware 2.1 released"), required_group))
check("every required term must hit, not just one",
      not mod.group_matches(item("ESP32 firmware"),
                            parse("ESP32\n+firmware\n+ota\n")[0][0]))
check("an excluded term blocks its own group",
      not mod.group_matches(item("ESP32 firmware engineer hiring"), excluding_group))
eq("an excluded term blocks that group only, not the others",
   [labels for _, labels in
    mod.select([item("ESP32 firmware engineer hiring")], REQ, [])],
   [["Firmware"]])


# --- one item, several groups; an item matching none is dropped -----------

MULTI, _ = parse("""\
ESP32
=> ESP32

firmware
=> Firmware

RISC-V
=> RISC-V
""")

selected = mod.select(
    [item("ESP32 firmware update"), item("Postgres 18 is out")], MULTI, [])
eq("only the matching item survives", len(selected), 1)
eq("it carries every group it matched, in file order",
   selected[0][1], ["ESP32", "Firmware"])
eq("the item itself comes back untouched",
   selected[0][0].title, "ESP32 firmware update")


# --- the shipped keyword file ---------------------------------------------

SHIPPED = pathlib.Path(__file__).resolve().parent.parent / "config" / "frequency_words.txt"
if SHIPPED.is_file():
    sgroups, sfilter = keywords.parse(SHIPPED)
    picked = mod.select([
        item("ESP32-C6 gets Zephyr support"),
        item("CVE-2026-9999 in an embedded TLS library"),
        item("Free giveaway: ten ESP32 boards"),
        item("Ranked: the best coffee in Hanoi"),
    ], sgroups, sfilter)
    titles = {i.title: labels for i, labels in picked}
    eq("the shipped file picks up the ESP32 story in two groups",
       titles.get("ESP32-C6 gets Zephyr support"), ["ESP32", "RTOS"])
    check("the shipped Security group needs its +embedded term",
          titles.get("CVE-2026-9999 in an embedded TLS library") == ["Security"])
    check("the shipped global filter drops the giveaway",
          "Free giveaway: ten ESP32 boards" not in titles)
    check("an unrelated story is dropped",
          "Ranked: the best coffee in Hanoi" not in titles)
else:
    FAILURES.append("config/frequency_words.txt is missing from the checkout")


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
