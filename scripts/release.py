#!/usr/bin/env python3
"""Publish a news-radar release.

    python scripts/release.py <version> [--dry-run] [--yes] [--remote origin]

Takes a version, writes the changelog and VERSION, commits it on the current
release/* branch as "chore(release): vX.Y.Z", merges release/* into developing
and developing into main, tags main, returns to release/*, and pushes.

Standard library only: this runs on a bare checkout. Every git call goes
through an argument list - no shell, so it behaves the same on Windows and
Linux.

Exit codes: 0 done, 1 preflight failed, 2 bad usage, 3 a git command failed.
See docs/memory-ai/rule/release-flow.md for the procedure this automates.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

def _utf8_stdout():
    """Print UTF-8 whatever the console claims its encoding is.

    `--dry-run` prints the changelog section it is about to publish, and this
    project's changelog is this project's own prose: a `Điện tử` in a P2 entry
    was enough to end the run with `UnicodeEncodeError` on a cp1252 Windows
    console, after the preflight had already passed. A release tool that cannot
    show the release is a release cut blind - and `release-flow.md` tells you to
    run `--dry-run` first, so the documented procedure was the broken one.

    Not a crash if it cannot be done: a stream that is already UTF-8, or one
    that is not a reconfigurable TextIOWrapper, is left exactly as it is.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


ROOT = Path(__file__).resolve().parent.parent

CHANGELOG = ROOT / "CHANGELOG.md"
VERSION_FILE = ROOT / "VERSION"

RELEASE_FILES = ["CHANGELOG.md", "VERSION"]

INTEGRATION_BRANCH = "developing"
STABLE_BRANCH = "main"
RELEASE_BRANCH_RE = re.compile(r"^release/")

VERSION_RE = re.compile(r"^[vV]?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

# The section entries are written into while the work happens. Matched
# loosely so "## Unreleased" survives casing and trailing whitespace.
UNRELEASED = "Unreleased"
UNRELEASED_RE = re.compile(r"^##\s+Unreleased\s*$", re.IGNORECASE)

CHANGELOG_HEADER = (
    "# Changelog\n"
    "\n"
    "Everything notable in this project, newest first.\n"
)


def say(tag, msg):
    print("[{}]{}{}".format(tag, " " * max(1, 6 - len(tag)), msg))


# --------------------------------------------------------------------------
# pure logic - everything below is covered by tests/test_release.py
# --------------------------------------------------------------------------


def normalise_version(raw):
    """'0.1.0' or 'v0.1.0' -> 'v0.1.0'. Anything else raises ValueError."""
    if not isinstance(raw, str):
        raise ValueError("version must be a string")
    m = VERSION_RE.match(raw.strip())
    if not m:
        raise ValueError(
            "version must look like 0.1.0 or v0.1.0, got {!r}".format(raw)
        )
    return "v{}.{}.{}".format(*m.groups())


def _unreleased_bounds(text):
    """(lines, start, end) around the Unreleased section, or None if absent.

    `start` is the heading line; `end` is the next '## ' heading, or EOF.
    """
    lines = (text or "").splitlines()
    start = None
    for i, line in enumerate(lines):
        if UNRELEASED_RE.match(line):
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return lines, start, end


def unreleased_body(text):
    """The Unreleased section's body, heading excluded.

    '' when the section exists but nothing has been recorded in it, None when
    there is no such section at all. The two are different problems.
    """
    found = _unreleased_bounds(text)
    if found is None:
        return None
    lines, start, end = found
    return "\n".join(lines[start + 1:end]).strip()


def promote_unreleased(text, version, date):
    """Rename Unreleased to the version and open a fresh empty Unreleased.

    Raises ValueError when the section is missing or empty: a release with
    nothing recorded is a mistake, not a valid empty release.
    """
    found = _unreleased_bounds(text)
    if found is None:
        raise ValueError("CHANGELOG.md has no '## {}' section".format(UNRELEASED))
    lines, start, end = found
    body = "\n".join(lines[start + 1:end]).strip()
    if not body:
        raise ValueError(
            "the {} section is empty - record what is being released "
            "before cutting it".format(UNRELEASED))

    promoted = [
        "## {}".format(UNRELEASED),
        "",
        "## {} - {}".format(version, date),
        "",
        body,
        "",
    ]
    return "\n".join(lines[:start] + promoted + lines[end:]).rstrip("\n") + "\n"


def extract_changelog_section(text, version):
    """The body of one version's block, heading line excluded. '' if absent."""
    marker = "## {} ".format(version)
    lines = (text or "").splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith(marker) or line.strip() == "## {}".format(version):
            start = i + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end]).strip() + "\n"


def release_commands(version, release_branch, remote):
    """The exact git chain, in execution order. Pure - runs nothing."""
    return [
        ["git", "add"] + RELEASE_FILES,
        ["git", "commit", "-m", "chore(release): {}".format(version)],
        ["git", "switch", INTEGRATION_BRANCH],
        ["git", "merge", "--no-ff", "-m",
         "chore(release): merge {} into {}".format(release_branch, INTEGRATION_BRANCH),
         release_branch],
        ["git", "switch", STABLE_BRANCH],
        ["git", "merge", "--no-ff", "-m",
         "chore(release): merge {} into {}".format(INTEGRATION_BRANCH, STABLE_BRANCH),
         INTEGRATION_BRANCH],
        ["git", "tag", "-a", version, "-m", version],
        ["git", "switch", release_branch],
        ["git", "push", remote, release_branch, INTEGRATION_BRANCH, STABLE_BRANCH],
        ["git", "push", remote, version],
    ]


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------


def git(*args, **kwargs):
    check = kwargs.pop("check", True)
    proc = subprocess.run(
        ["git"] + list(args), cwd=str(ROOT), capture_output=True, text=True, check=False
    )
    if check and proc.returncode != 0:
        raise RuntimeError("git {}: {}".format(" ".join(args), (proc.stderr or proc.stdout).strip()))
    return proc


def current_branch():
    return git("branch", "--show-current").stdout.strip()


def working_tree_clean():
    return git("status", "--porcelain").stdout.strip() == ""


def branch_exists(name):
    return git("rev-parse", "--verify", "--quiet", "refs/heads/" + name, check=False).returncode == 0


def tag_exists(name, remote):
    """True when the tag exists locally or on the remote the release will push to."""
    if git("rev-parse", "--verify", "--quiet", "refs/tags/" + name, check=False).returncode == 0:
        return True
    proc = git("ls-remote", "--tags", remote, name, check=False)
    return bool(proc.stdout.strip())


def preflight(version, strict, remote):
    """Report every check. Returns True when the release may proceed."""
    ok = True

    branch = current_branch()
    if RELEASE_BRANCH_RE.match(branch):
        say("ok", "on {}".format(branch))
    else:
        say("warn" if not strict else "fail",
            "current branch is {!r}, expected release/*".format(branch))
        ok = False

    if working_tree_clean():
        say("ok", "working tree clean")
    else:
        say("warn" if not strict else "fail", "working tree has uncommitted changes")
        ok = False

    for name in (INTEGRATION_BRANCH, STABLE_BRANCH):
        if branch_exists(name):
            say("ok", "branch {} exists".format(name))
        else:
            say("warn" if not strict else "fail", "branch {} does not exist".format(name))
            ok = False

    if tag_exists(version, remote):
        say("warn" if not strict else "fail", "tag {} already exists".format(version))
        ok = False
    else:
        say("ok", "tag {} is free".format(version))

    body = unreleased_body(read_changelog())
    if body is None:
        say("warn" if not strict else "fail",
            "{} has no '## {}' section".format(CHANGELOG.name, UNRELEASED))
        ok = False
    elif not body:
        say("warn" if not strict else "fail",
            "nothing recorded under {} - there is no release to cut".format(UNRELEASED))
        ok = False
    else:
        entries = len([l for l in body.splitlines() if l.lstrip().startswith("- ")])
        say("ok", "{} entr{} under {}".format(
            entries, "y" if entries == 1 else "ies", UNRELEASED))

    return ok


def read_changelog():
    return CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.is_file() else ""


# --------------------------------------------------------------------------


def main(argv=None):
    # Before anything is printed, including the preflight lines.
    _utf8_stdout()
    parser = argparse.ArgumentParser(
        prog="release.py",
        description="Cut a news-radar release: changelog, commit, merge chain, tag, push.",
    )
    parser.add_argument("version", help="version to release, e.g. 0.1.0 or v0.1.0")
    parser.add_argument("--dry-run", action="store_true",
                        help="touch nothing; print the git chain and exit")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--remote", default="origin", help="push target (default: origin)")
    args = parser.parse_args(argv)

    try:
        version = normalise_version(args.version)
    except ValueError as e:
        say("fail", str(e))
        return 2

    branch = current_branch() or "release/<branch>"
    date = _dt.date.today().isoformat()

    print("news-radar release {}  (branch {}, remote {})".format(version, branch, args.remote))

    # Preflight is advisory under --dry-run: the point of a dry run is to see
    # the plan, including from a branch that could not release yet.
    passed = preflight(version, strict=not args.dry_run, remote=args.remote)

    body = unreleased_body(read_changelog())
    commands = release_commands(version, branch, args.remote)

    if args.dry_run:
        if body:
            print("\nwould promote {} to '## {} - {}':\n".format(
                UNRELEASED, version, date))
            for line in body.splitlines():
                print("    " + line)
        else:
            print("\nnothing to promote - {} is empty or missing".format(UNRELEASED))
        print("\nwould run, in order:\n")
        for cmd in commands:
            print("    " + " ".join(cmd))
        print()
        say("dry", "nothing was written")
        return 0

    if not passed:
        say("fail", "preflight failed - nothing was changed")
        return 1

    print("\nwill run, in order:\n")
    for cmd in commands:
        print("    " + " ".join(cmd))
    print()
    if not args.yes:
        try:
            answer = input("proceed? this pushes {} and {} [y/N]: ".format(
                INTEGRATION_BRANCH, STABLE_BRANCH)).strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            say("warn", "aborted - nothing was changed")
            return 1

    try:
        promoted = promote_unreleased(read_changelog(), version, date)
    except ValueError as exc:
        say("fail", str(exc))
        return 1
    CHANGELOG.write_text(promoted, encoding="utf-8")
    say("new", "{} - {} promoted to {}".format(CHANGELOG.name, UNRELEASED, version))
    VERSION_FILE.write_text(version.lstrip("v") + "\n", encoding="utf-8")
    say("new", "{} = {}".format(VERSION_FILE.name, version.lstrip("v")))

    for cmd in commands:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            say("fail", " ".join(cmd))
            print((proc.stderr or proc.stdout).strip())
            say("fail", "stopped here - inspect the repository before re-running")
            return 3
        say("ok", " ".join(cmd))

    print()
    say("ok", "released {} - CI will publish the GitHub Release from the tag".format(version))
    return 0


if __name__ == "__main__":
    sys.exit(main())
