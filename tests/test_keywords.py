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


# --- a regex-only group, and why it exists --------------------------------

# `fold("RTOs") == fold("RTOS")`, so a plain term can never separate an RTOS
# story from an Indian Regional Transport Office. A regex can - it runs on the
# original title - but `filter.group_matches()` ORs terms with regexes, so a
# regex only ever *widens* a group. The loose plain term therefore has to go,
# and the search query has to come from somewhere else: the label.
rx_groups, _ = mod.parse(write("/\\bRTOS\\b/\n/\\bZephyr\\b/\n@8\n=> RTOS\n"))
rx = rx_groups[0]
eq("a regex-only group parses", len(rx_groups), 1)
eq("it has no plain term at all", rx.terms, [])
eq("both regexes survive", len(rx.regexes), 2)
eq("its search query comes from the label", rx.primary, "RTOS")
eq("...and the label is still the label", rx.label, "RTOS")
eq("the cap survives too", rx.cap, 8)

# The point of the whole exercise, checked end to end through the real filter.
from news_radar.filter import group_matches  # noqa: E402
from news_radar.item import new_item  # noqa: E402
import datetime as _dt  # noqa: E402

_NOW = _dt.datetime(2026, 9, 7, tzinfo=_dt.timezone.utc)


def _matches(group, title):
    return group_matches(new_item(title, "https://e.invalid/x", "hn", _NOW), group)


check("the real RTOS story still matches",
      _matches(rx, "Async Rust vs RTOS showdown (2022)"))
check("...and so does the Zephyr one",
      _matches(rx, "Simplifying Embedded System Design with Zephyr RTOS - EE Times"))
check("the Indian transport office does not",
      not _matches(rx, "Ahmedabad RTOs hit by technical glitches, 12K pending"))
check("...nor the bribery story",
      not _matches(rx, "Former transport commissioner alleges RTOs pocket Rs 1,700 crore"))

# The thing that made the old advice a no-op: adding a regex beside the loose
# plain term changes nothing, because the two are OR-ed.
loose, _ = mod.parse(write("RTOS\n/\\bRTOS\\b/\n@8\n=> RTOS\n"))
check("a regex beside a loose plain term cannot narrow a group - it only widens",
      _matches(loose[0], "Ahmedabad RTOs hit by technical glitches, 12K pending"))
eq("...and that group's query is still the plain term", loose[0].primary, "RTOS")

# A label is a display string doing a second job here, so a space in it travels
# into the query as a quoted phrase. Pinned so that stays a decision.
spaced, _ = mod.parse(write("/\\bTinyML\\b/\n=> tiny ml\n"))
eq("a spaced label becomes the query verbatim", spaced[0].primary, "tiny ml")
from news_radar.fetch.search import build_urls  # noqa: E402

_url = build_urls(spaced, [{"id": "t", "url": "https://e.invalid/?q={kw}"}])[0][0]
check("...and search quotes it as a phrase", "%22tiny+ml%22" in _url, _url)


# --- the errors that would otherwise be silent ----------------------------

msg = check_raises("a group with neither a plain term nor a labelled regex "
                   "is rejected",
                   write("ESP32\n\n!only-an-exclusion\n@5\n"))
check("the rejection names the line number", ":3" in msg or "line 3" in msg, msg)
check("...and says both ways out", "regex" in msg and "Label" in msg, msg)

# An unlabelled regex-only group has nothing to search for and nothing to
# call itself, so it is still refused - the label is doing double duty as
# the query.
check_raises("a regex-only group with no => label is rejected",
             write("ESP32\n\n/\\\\bRTOS\\\\b/\n@5\n"))

check_raises("a non-numeric cap is rejected", write("ESP32\n@many\n"))
check_raises("an unterminated regex is rejected", write("ESP32\n/CVE-\\d+\n"))
check_raises("an invalid regex is rejected", write("ESP32\n/CVE-[/\n"))
check_raises("a missing file is rejected", TMP / "does-not-exist.txt")
check_raises("a file with no group at all is rejected",
             write("# only comments\n\n[GLOBAL_FILTER]\n!x\n"))


# --- the committed file ---------------------------------------------------

# The template, not the working copy. `config/frequency_words.txt` is a local
# file a deployment is free to tune and is gitignored for exactly that reason,
# so it is not in a CI checkout at all - `.example` is what ships.
shipped = (pathlib.Path(__file__).resolve().parent.parent
           / "config" / "frequency_words.txt.example")
if shipped.is_file():
    sgroups, sfilter = mod.parse(shipped)
    eq("the shipped keyword template parses into 13 groups", len(sgroups), 13)
    eq("its primary terms are the ones the search templates will query",
       [g.primary for g in sgroups],
       ["ESP32", "STM32", "firmware", "RISC-V", "AI Model Release", "Claude",
        "ChatGPT", "GLM", "Qwen", "DeepSeek", "artificial intelligence",
        "open source AI", "GitHub Trending"])
    # ESP32, AI and AI Repos were widened when the template took on six more
    # feeds. The five model groups are narrow topics and get @6 apiece.
    eq("its caps survive the parse",
       [g.cap for g in sgroups],
       [12, 10, 10, 8, 10, 6, 6, 6, 6, 6, 12, 10, 8])

    # STM32 is the other half of "firmware for ESP and STM". Its primary term
    # is what the search templates query, which is the whole point of giving it
    # a group instead of adding STM32 to the ESP32 one.
    check("STM32 is its own group, so it gets its own search query",
          "STM32" in [g.primary for g in sgroups], repr(
              [g.primary for g in sgroups]))

    # Load-bearing order: `notify.pick()` sends a story under the FIRST group
    # in this file that claims it, and a Claude story matches the AI group too.
    # Ahead of it, the message says "Claude"; behind it, "AI".
    labels = [g.label for g in sgroups]
    check("every model group sits ahead of the AI group",
          all(labels.index(v) < labels.index("AI")
              for v in ("Claude", "ChatGPT", "GLM", "Qwen", "DeepSeek")),
          repr(labels))
    check("its global filter still blocks the advertising terms",
          {"giveaway", "coupon", "khuyen mai", "sponsored"} <= set(sfilter),
          repr(sfilter))
    # Measured 2026-09-12 in the live store: the model-vendor groups were
    # pulling in Zcash whale trades, SK Hynix share moves and DeepSeek IPO
    # filings. `crypto` and `ipo` are deliberately absent - matching is
    # substring, so they would eat `cryptography` and `LiPo`.
    check("...and the crypto and market noise measured on the live store",
          {"zcash", "bitcoin", "cryptocurrency", "memecoin"} <= set(sfilter),
          repr(sfilter))
    check("no global exclusion is a substring trap",
          not ({"crypto", "ipo", "tv"} & set(sfilter)), repr(sfilter))
    check("every group has a non-empty label",
          all(g.label for g in sgroups))

    # The two AI groups are the only ones that cannot be written as plain
    # terms. Matching is substring, so a bare `AI` would hit said, maintain,
    # chain, fail, email and Ukraine; the word boundary lives in a regex, run
    # against the original title. If that regex is ever lost the groups do not
    # break loudly - they quietly match a great deal less - so it is pinned.
    by_label = {g.label: g for g in sgroups}
    ai, repos = by_label["AI"], by_label["AI Repos"]
    eq("the AI group carries its word-boundary regex", len(ai.regexes), 1)
    check("...which matches a bare AI token",
          ai.regexes[0].search("Google races ahead in AI"))
    check("...and A.I. written with periods",
          ai.regexes[0].search("District Bans Most A.I. For Students"))
    check("...but not the ai inside an ordinary word",
          not ai.regexes[0].search("He said the chain of failures was detailed"))
    eq("the AI Repos group carries its Show HN regex", len(repos.regexes), 1)
    check("...which matches an AI project launch",
          repos.regexes[0].search("Show HN: Argus, open-source AI agents"))
    check("...but not a Show HN with nothing to do with AI",
          not repos.regexes[0].search("Show HN: Md2pdf - Markdown to PDF"))

    # A model release is what the request asked to hunt, and it cannot be a
    # plain term: `release` matches every ESP-IDF tag and every camera
    # firmware. Two regexes - a versioned model name, and a release verb next
    # to a model word - and they are pinned for the same reason the AI ones
    # are: losing one costs matches quietly.
    release = by_label["AI Model Release"]
    eq("the model-release group is regex-only", len(release.terms), 0)
    eq("...with two regexes", len(release.regexes), 2)
    hits = lambda t: any(rx.search(t) for rx in release.regexes)
    check("...matching a versioned model name",
          hits("Qwen3.8 Max Debuts With 2.4 Trillion Parameters"))
    check("...and a release verb beside a model word",
          hits("Alibaba's Qwen releases open-source model for driving"))
    check("...and DeepSeek's own version scheme",
          hits("China's DeepSeek launches V4.1-Flash model"))
    check("...but not an ESP-IDF tag",
          not hits("ESP-IDF Release v5.2.8"))
    check("...and not a camera firmware release",
          not hits("Canon Announces Firmware Updates for PTZ Camera Lineup"))

    # The Firmware group is the one the request named, and the bare word
    # belongs to every consumer device: measured 2026-09-12, 36 of its 94 live
    # matches were Nikon, Canon, Sony, PlayStation or AirPods firmware.
    fw = by_label["Firmware"]
    check("the firmware group excludes the consumer devices it was drowning in",
          {"nikon", "canon", "camera", "playstation", "airpods"}
          <= {e.lower() for e in fw.excluded}, repr(fw.excluded))
else:
    FAILURES.append(
        "config/frequency_words.txt.example is missing from the checkout")


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
