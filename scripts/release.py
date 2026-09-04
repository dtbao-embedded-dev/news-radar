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

ROOT = Path(__file__).resolve().parent.parent

CHANGELOG = ROOT / "CHANGELOG.md"
VERSION_FILE = ROOT / "VERSION"

RELEASE_FILES = ["CHANGELOG.md", "VERSION"]

INTEGRATION_BRANCH = "developing"
STABLE_BRANCH = "main"
RELEASE_BRANCH_RE = re.compile(r"^release/")

VERSION_RE = re.compile(r"^[vV]?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

# "type(scope)!: description" - scope and the breaking bang are optional.
SUBJECT_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s*(?P<desc>.+)$")

# A release commit describes the release, not what is in it.
RELEASE_SUBJECT_RE = re.compile(r"^chore\(release\):\s*v?\d+\.\d+\.\d+\s*$")

CHANGELOG_HEADER = "# Changelog\n\nEverything notable in this project, newest first.\n"

# Heading order in a section. Anything unlisted falls into "other".
SECTION_ORDER = [
    ("breaking", "Breaking Changes"),
    ("feat", "Features"),
    ("fix", "Fixes"),
    ("perf", "Performance"),
    ("refactor", "Refactoring"),
    ("docs", "Documentation"),
    ("build", "Build"),
    ("ci", "CI"),
    ("test", "Tests"),
    ("style", "Style"),
    ("chore", "Chores"),
    ("other", "Other"),
]


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


def parse_subjects(subjects):
    """Conventional-commit subjects -> dicts. Release commits are dropped."""
    out = []
    for raw in subjects:
        subject = raw.strip()
        if not subject or RELEASE_SUBJECT_RE.match(subject):
            continue
        m = SUBJECT_RE.match(subject)
        if m:
            out.append({
                "type": m.group("type"),
                "scope": m.group("scope"),
                "description": m.group("desc").strip(),
                "breaking": bool(m.group("bang")),
            })
        else:
            # Kept rather than dropped: a release note that silently omits a
            # commit is worse than one with an untyped line in it.
            out.append({
                "type": "other",
                "scope": None,
                "description": subject,
                "breaking": False,
            })
    return out


def build_changelog_section(version, date, commits):
    """One '## <version> - <date>' block, grouped by type, breaking first."""
    buckets = {}
    for c in commits:
        key = "breaking" if c["breaking"] else c["type"]
        if key not in dict(SECTION_ORDER):
            key = "other"
        buckets.setdefault(key, []).append(c)

    lines = ["## {} - {}".format(version, date), ""]
    if not commits:
        lines.append("No changes recorded.")
        lines.append("")
    for key, title in SECTION_ORDER:
        entries = buckets.get(key)
        if not entries:
            continue
        lines.append("### {}".format(title))
        lines.append("")
        for c in entries:
            scope = "**{}**: ".format(c["scope"]) if c["scope"] else ""
            lines.append("- {}{}".format(scope, c["description"]))
        lines.append("")
    return "\n".join(lines) + "\n"


def insert_changelog_section(existing, section):
    """Put section directly under the preamble, above the previous newest."""
    text = existing or ""
    if not text.strip():
        return CHANGELOG_HEADER + "\n" + section

    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("## "):
            return "".join(lines[:i]) + section + "\n" + "".join(lines[i:])

    # A changelog with a preamble but no releases yet.
    tail = "" if text.endswith("\n") else "\n"
    return text + tail + "\n" + section


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


def tag_exists(name):
    if git("rev-parse", "--verify", "--quiet", "refs/tags/" + name, check=False).returncode == 0:
        return True
    remote = git("ls-remote", "--tags", "origin", name, check=False)
    return bool(remote.stdout.strip())


def previous_tag():
    proc = git("describe", "--tags", "--abbrev=0", check=False)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def commit_subjects_since(tag):
    span = "{}..HEAD".format(tag) if tag else "HEAD"
    proc = git("log", span, "--no-merges", "--pretty=%s", check=False)
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def preflight(version, strict):
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

    if tag_exists(version):
        say("warn" if not strict else "fail", "tag {} already exists".format(version))
        ok = False
    else:
        say("ok", "tag {} is free".format(version))

    return ok


# --------------------------------------------------------------------------


def main(argv=None):
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
    passed = preflight(version, strict=not args.dry_run)

    prev = previous_tag()
    commits = parse_subjects(commit_subjects_since(prev))
    say("ok", "{} commit(s) since {}".format(len(commits), prev or "the first commit"))

    section = build_changelog_section(version, date, commits)
    commands = release_commands(version, branch, args.remote)

    if args.dry_run:
        print("\nwould write {} and {}:\n".format(CHANGELOG.name, VERSION_FILE.name))
        for line in section.rstrip("\n").splitlines():
            print("    " + line)
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

    existing = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.is_file() else ""
    CHANGELOG.write_text(insert_changelog_section(existing, section), encoding="utf-8")
    say("new", "{} updated".format(CHANGELOG.name))
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
