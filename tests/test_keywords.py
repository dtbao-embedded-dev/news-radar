#!/usr/bin/env python3
"""Checks for src/news_radar/keywords.py - plain asserts, no test framework.

    python tests/test_keywords.py

Standard library only. Writes its fixture to a temp directory, then checks the
repository's own config/frequency_words.txt against the same parser - the
committed file has to satisfy its own contract, the way test_config.py checks
config.yaml.example.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar import keywords as mod  # noqa: E402

FAILURES = []
TMP = pathlib.Path(tempfile.mkdtemp(prefix="news-radar-keywords-"))
COUNTER = [0]


def check(name, condition, detail=""):
    if not condition:
        FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def eq(name, got, want):
    check(name, got == want, "got {!r}, want {!r}".format(got, want))


def write(text):
    COUNTER[0] += 1
    path = TMP / "kw{}.txt".format(COUNTER[0])
    path.write_text(text, encoding="utf-8")
    return path


def check_raises(name, path):
    try:
        mod.parse(path)
    except mod.KeywordError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001
        FAILURES.append("{}: raised {!r}, expected KeywordError".format(name, exc))
        return ""
    FAILURES.append("{}: did not raise KeywordError".format(name))
    return ""


# --- the full syntax ------------------------------------------------------

FULL = write("""\
# a leading comment, and a blank line after it

ESP32
ESP-IDF
+embedded
!tuyen dung
/CVE-\\d{4}-\\d+/
@10
=> ESP32 news

RTOS
FreeRTOS

[GLOBAL_FILTER]
!giveaway
!coupon
""")

groups, gfilter = mod.parse(FULL)

eq("two groups parsed, the global filter is not one of them", len(groups), 2)

g = groups[0]
eq("the first plain line is the primary term", g.primary, "ESP32")
eq("plain lines become terms, in order", g.terms, ["ESP32", "ESP-IDF"])
eq("+ lines become required", g.required, ["embedded"])
eq("! lines become excluded", g.excluded, ["tuyen dung"])
eq("@n becomes the cap", g.cap, 10)
eq("=> becomes the label", g.label, "ESP32 news")
eq("one regex compiled", len(g.regexes), 1)
check("the regex is applied to the original title, not the folded one",
      g.regexes[0].search("Fix for CVE-2026-1234") is not None)
check("the regex is not a term as well",
      "/CVE-\\d{4}-\\d+/" not in g.terms)

g2 = groups[1]
eq("a group with no @n has no cap", g2.cap, None)
eq("a group with no => labels itself with its primary term", g2.label, "RTOS")
eq("a group with no + has no required terms", g2.required, [])

eq("the global filter collects its ! lines", gfilter, ["giveaway", "coupon"])

eq("blank lines around and comments inside do not create empty groups",
   [x.primary for x in mod.parse(write(
       "\n\n# c\nESP32\n\n\n# another\nRTOS\n# trailing\n\n"))[0]],
   ["ESP32", "RTOS"])

eq("a file with no global filter section yields an empty filter",
   mod.parse(write("ESP32\n"))[1], [])

eq("whitespace around a line is ignored",
   mod.parse(write("  ESP32  \n  @5 \n  =>  Label  \n"))[0][0].label, "Label")

# A comment starts the line. An inline # belongs to the term, or the keyword
# "C# programming" would be truncated to "C" and match every title there is.
eq("an inline hash stays part of the term",
   mod.parse(write("C# programming\n"))[0][0].primary, "C# programming")
eq("a comment line inside a group does not end the group",
   mod.parse(write("ESP32\n# still the same group\nESP-IDF\n"))[0][0].terms,
   ["ESP32", "ESP-IDF"])


# --- the errors that would otherwise be silent ----------------------------

msg = check_raises("a group with no plain term is rejected",
                   write("ESP32\n\n!only-an-exclusion\n@5\n"))
check("the rejection names the line number", ":3" in msg or "line 3" in msg, msg)

check_raises("a non-numeric cap is rejected", write("ESP32\n@many\n"))
check_raises("an unterminated regex is rejected", write("ESP32\n/CVE-\\d+\n"))
check_raises("an invalid regex is rejected", write("ESP32\n/CVE-[/\n"))
check_raises("a missing file is rejected", TMP / "does-not-exist.txt")
check_raises("a file with no group at all is rejected",
             write("# only comments\n\n[GLOBAL_FILTER]\n!x\n"))


# --- the committed file ---------------------------------------------------

shipped = pathlib.Path(__file__).resolve().parent.parent / "config" / "frequency_words.txt"
if shipped.is_file():
    sgroups, sfilter = mod.parse(shipped)
    eq("config/frequency_words.txt parses into 7 groups", len(sgroups), 7)
    eq("its primary terms are the ones the search templates will query",
       [g.primary for g in sgroups],
       ["ESP32", "firmware", "RTOS", "embedded linux", "RISC-V",
        "Rust embedded", "CVE"])
    eq("its caps survive the parse",
       [g.cap for g in sgroups], [10, 10, 8, 8, 8, 6, 6])
    eq("its global filter has four exclusions", len(sfilter), 4)
    check("every group has a non-empty label",
          all(g.label for g in sgroups))
    check("the Security group keeps its required term",
          sgroups[6].required == ["embedded"])
else:
    FAILURES.append("config/frequency_words.txt is missing from the checkout")


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
