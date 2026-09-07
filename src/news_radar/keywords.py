"""Parse config/frequency_words.txt into keyword groups and the global filter.

A leaf module: standard library only, no import from the rest of the package.
`fetch/search.py` needs each group's primary term to build a search URL;
`filter.py` needs the whole group to decide what an item matched.

Contract: docs/memory-ai/interface/config-and-env.md (keyword-file syntax)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = ["KeywordGroup", "KeywordError", "parse", "GLOBAL_FILTER_HEADER"]

GLOBAL_FILTER_HEADER = "[GLOBAL_FILTER]"


class KeywordError(Exception):
    """Refuse a keyword file rather than hunt with half of it."""


@dataclass
class KeywordGroup:
    """One block of the file: what it matches, what it forbids, how many it keeps."""

    primary: str
    label: str
    terms: list = field(default_factory=list)
    required: list = field(default_factory=list)
    excluded: list = field(default_factory=list)
    regexes: list = field(default_factory=list)
    cap: int | None = None


def _finish(lines, path):
    """Turn one block of (line_number, text) into a KeywordGroup."""
    group = KeywordGroup(primary="", label="")
    for lineno, text in lines:
        if text.startswith("=>"):
            group.label = text[2:].strip()
        elif text.startswith("@"):
            digits = text[1:].strip()
            if not digits.isdigit():
                raise KeywordError(
                    "{}:{}: @n cap must be a number, got {!r}".format(
                        path, lineno, text))
            group.cap = int(digits)
        elif text.startswith("+"):
            group.required.append(text[1:].strip())
        elif text.startswith("!"):
            group.excluded.append(text[1:].strip())
        elif text.startswith("/"):
            if not text.endswith("/") or len(text) < 3:
                raise KeywordError(
                    "{}:{}: a regex line must be wrapped in slashes: {!r}".format(
                        path, lineno, text))
            try:
                group.regexes.append(re.compile(text[1:-1]))
            except re.error as exc:
                raise KeywordError("{}:{}: invalid regex {!r}: {}".format(
                    path, lineno, text, exc)) from exc
        else:
            group.terms.append(text)

    # `primary` is the string every search template queries. Two ways to give
    # the group one, and the second exists because the first cannot express a
    # narrow match.
    #
    # A plain term is matched on the **folded** title, so it can never be made
    # case- or boundary-sensitive: `fold("RTOs") == fold("RTOS")`, and the
    # `RTOS` group spent a day carrying Indian Regional Transport Offices
    # because of it. `/\bRTOS\b/` separates them exactly - but a regex only
    # ever *widens* a group (`filter.group_matches()` ORs the two), so the
    # loose plain term has to go, and then there was nothing left to search
    # for. A regex-only group takes its query from its `=> Label` instead.
    if group.terms:
        group.primary = group.terms[0]
    elif group.regexes and group.label:
        # The label is a display string doing a second job here, which is worth
        # knowing when writing one: it travels into the search URL verbatim, so
        # a label with a space is sent as a quoted phrase.
        group.primary = group.label
    else:
        # A group with no plain term and no labelled regex produces no search
        # URL and matches nothing a human would recognise. Left to itself it
        # would just quietly vanish from the report, which is the failure that
        # costs an afternoon.
        raise KeywordError(
            "{}:{}: group has nothing to search for - give it a plain term "
            "(the first one is its primary term and the one the search "
            "templates query), or a /regex/ plus a '=> Label' to query "
            "instead".format(path, lines[0][0]))

    group.label = group.label or group.primary
    return group


def parse(path):
    """Read the keyword file. Returns (groups, global_filter_terms).

    Blocks are separated by a blank line; `#` starts a comment; the
    `[GLOBAL_FILTER]` block is not a group - its `!` lines apply to every item
    from every source, before any group is considered.
    """
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as exc:
        raise KeywordError("cannot read keyword file {}: {}".format(path, exc)) from exc

    groups = []
    global_filter = []
    block = []
    in_global = False

    def flush():
        nonlocal in_global, block
        if block:
            if in_global:
                # Only exclusions are meaningful here: the section says what
                # never gets through, not what to hunt for.
                global_filter.extend(t[1:].strip() for _, t in block
                                     if t.startswith("!"))
            else:
                groups.append(_finish(block, path))
        block = []
        in_global = False

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        # A comment starts the line, as the file's own header documents. An
        # inline `#` is part of the term: "C# programming" is a keyword someone
        # will write, and truncating it to "C" would match every title.
        if line.startswith("#"):
            continue
        if not line:
            flush()
            continue
        if line == GLOBAL_FILTER_HEADER:
            flush()
            in_global = True
            continue
        block.append((lineno, line))
    flush()

    if not groups:
        raise KeywordError(
            "{}: no keyword group found - nothing to hunt for".format(path))

    return groups, global_filter
