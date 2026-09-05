#!/usr/bin/env python3
"""Checks for scripts/release.py - plain asserts, no test framework.

    python tests/test_release.py

Covers only the pure logic: version parsing, the git command chain, and the
changelog promote/extract round trip. Nothing here runs git, and nothing here
reads the repository's own CHANGELOG.md.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

import release  # noqa: E402

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        return
    FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def check_raises(name, exc, fn, *args):
    try:
        fn(*args)
    except exc:
        return
    except Exception as e:  # noqa: BLE001 - wrong exception is a failure, not a crash
        FAILURES.append("{}: raised {!r}, expected {}".format(name, e, exc.__name__))
        return
    FAILURES.append("{}: did not raise {}".format(name, exc.__name__))


# --------------------------------------------------------------------------
# version parsing
# --------------------------------------------------------------------------

check("bare version gains the v", release.normalise_version("0.1.0") == "v0.1.0")
check("prefixed version stays", release.normalise_version("v0.1.0") == "v0.1.0")
check("capital V accepted", release.normalise_version("V2.10.3") == "v2.10.3")
check("surrounding space tolerated", release.normalise_version("  1.0.0 ") == "v1.0.0")

for bad in ["0.1", "1.2.3.4", "abc", "v", "", "1.2.x", "01.2.3-rc1"]:
    check_raises("reject {!r}".format(bad), ValueError, release.normalise_version, bad)


# --------------------------------------------------------------------------
# the git chain
# --------------------------------------------------------------------------

cmds = release.release_commands("v0.1.0", "release/v0.1", "origin")
flat = [" ".join(c) for c in cmds]

check("every command is a git argv list",
      all(isinstance(c, list) and c and c[0] == "git" for c in cmds))

check("nothing goes through a shell",
      all(all(isinstance(part, str) for part in c) for c in cmds))

check("release commit message is exact",
      ["git", "commit", "-m", "chore(release): v0.1.0"] in cmds,
      "got: {}".format(flat))

def index_of(prefix):
    for i, line in enumerate(flat):
        if line.startswith(prefix):
            return i
    return -1

i_add = index_of("git add")
i_commit = index_of("git commit")
i_dev = index_of("git switch developing")
i_merge_rel = index_of("git merge --no-ff")
i_main = index_of("git switch main")
i_tag = index_of("git tag")
i_back = index_of("git switch release/v0.1")
i_push = index_of("git push")

for name, idx in [("add", i_add), ("commit", i_commit), ("switch developing", i_dev),
                  ("merge", i_merge_rel), ("switch main", i_main), ("tag", i_tag),
                  ("switch back", i_back), ("push", i_push)]:
    check("chain contains {}".format(name), idx >= 0, "missing from: {}".format(flat))

check("stage before commit", i_add < i_commit)
check("commit lands on the release branch, before any switch", i_commit < i_dev)
check("developing is merged before main is touched", i_dev < i_main)
check("tag is created while on main", i_main < i_tag)
check("chain returns to the release branch after tagging", i_tag < i_back)
check("push is last", i_push == max(i_add, i_commit, i_dev, i_main, i_tag, i_back, i_push)
      or i_push > i_back)

merges = [c for c in cmds if c[:2] == ["git", "merge"]]
check("two merges, both --no-ff", len(merges) == 2 and all("--no-ff" in m for m in merges),
      "got: {}".format(merges))
check("release branch merges into developing", "release/v0.1" in merges[0])
check("developing merges into main", "developing" in merges[1])

pushes = [c for c in cmds if c[:2] == ["git", "push"]]
check("push targets the configured remote", all("origin" in p for p in pushes))
check("all three branches are pushed",
      all(any(b in p for p in pushes) for b in ["release/v0.1", "developing", "main"]))
check("the tag is pushed", any("v0.1.0" in p for p in pushes))

alt = release.release_commands("v9.9.9", "release/v9.9", "upstream")
check("remote is honoured", all("upstream" in c for c in alt if c[:2] == ["git", "push"]))
check("release branch name is honoured", any("release/v9.9" in " ".join(c) for c in alt))


# --------------------------------------------------------------------------
# changelog - hand-written Unreleased section, not derived from commits
# --------------------------------------------------------------------------

NO_SECTION = "# Changelog\n\nPreamble only.\n"

EMPTY_SECTION = (
    "# Changelog\n"
    "\n"
    "Preamble.\n"
    "\n"
    "## Unreleased\n"
    "\n"
    "## v0.0.9 - 2026-08-01\n"
    "\n"
    "### Fixes\n"
    "\n"
    "- an older fix\n"
)

FILLED = (
    "# Changelog\n"
    "\n"
    "Preamble.\n"
    "\n"
    "## Unreleased\n"
    "\n"
    "### Features\n"
    "\n"
    "- **fetch**: add the rss reader\n"
    "\n"
    "### Fixes\n"
    "\n"
    "- survive a 403 from reddit\n"
    "\n"
    "## v0.0.9 - 2026-08-01\n"
    "\n"
    "### Fixes\n"
    "\n"
    "- an older fix\n"
)

check("no Unreleased section reads as None",
      release.unreleased_body(NO_SECTION) is None)
check("an empty Unreleased section reads as empty, not None",
      release.unreleased_body(EMPTY_SECTION) == "")
check("a filled section returns its body",
      "add the rss reader" in release.unreleased_body(FILLED))
check("the body stops at the next version heading",
      "an older fix" not in release.unreleased_body(FILLED),
      "got: {!r}".format(release.unreleased_body(FILLED)))
check("the heading itself is not part of the body",
      not release.unreleased_body(FILLED).lower().startswith("## unreleased"))
check("casing and trailing space on the heading still match",
      release.unreleased_body("## UNRELEASED  \n\n- x\n") == "- x")


# --- the tool must be able to print the release it is about to cut ---------

# `--dry-run` prints the changelog section, and this project's changelog is
# this project's own prose. A `Điện tử` in a P2 entry ended the run with
# UnicodeEncodeError on a cp1252 Windows console - after the preflight had
# passed, and in the one command release-flow.md tells you to run first.
release._utf8_stdout()
encoding = (sys.stdout.encoding or "").lower().replace("-", "")
check("stdout is reconfigured to UTF-8 before anything is printed",
      encoding.startswith("utf"), repr(sys.stdout.encoding))

body = release.unreleased_body(release.read_changelog())
try:
    body.encode(sys.stdout.encoding or "utf-8")
    printable = True
except (UnicodeEncodeError, LookupError):
    printable = False
check("the real Unreleased section survives the console encoding", printable)

check_raises("promoting a missing section raises", ValueError,
             release.promote_unreleased, NO_SECTION, "v0.1.0", "2026-09-05")
check_raises("promoting an empty section raises", ValueError,
             release.promote_unreleased, EMPTY_SECTION, "v0.1.0", "2026-09-05")

promoted = release.promote_unreleased(FILLED, "v0.1.0", "2026-09-05")

check("preamble survives", promoted.startswith("# Changelog"))
check("the version heading is written", "## v0.1.0 - 2026-09-05" in promoted)
check("a fresh empty Unreleased is opened", "## Unreleased" in promoted)
check("Unreleased sits above the new version",
      promoted.index("## Unreleased") < promoted.index("## v0.1.0"))
check("newest version first",
      promoted.index("## v0.1.0") < promoted.index("## v0.0.9"))
check("the promoted body moved with the version",
      promoted.index("add the rss reader") > promoted.index("## v0.1.0")
      and promoted.index("add the rss reader") < promoted.index("## v0.0.9"))
check("the older release survives untouched", "an older fix" in promoted)
check("the new Unreleased is empty", release.unreleased_body(promoted) == "",
      "got: {!r}".format(release.unreleased_body(promoted)))
check_raises("a second promote with nothing recorded raises", ValueError,
             release.promote_unreleased, promoted, "v0.2.0", "2026-09-06")
check("file ends with exactly one newline",
      promoted.endswith("\n") and not promoted.endswith("\n\n"))

notes = release.extract_changelog_section(promoted, "v0.1.0")
check("extract returns only the requested version", "an older fix" not in notes)
check("extract keeps the body", "add the rss reader" in notes)
check("extract drops the version heading line",
      not notes.lstrip().startswith("## v0.1.0"),
      "notes start: {!r}".format(notes[:40]))
check("extract does not bleed into Unreleased",
      "Unreleased" not in notes)
check("extract of a missing version is empty",
      release.extract_changelog_section(promoted, "v7.7.7").strip() == "")


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
