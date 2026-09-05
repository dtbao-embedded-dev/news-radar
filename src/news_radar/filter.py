"""Decide what gets through, and which keyword groups it belongs to.

Layer 3 - the first half of selection. It reads `NewsItem` and `KeywordGroup`
and nothing else: no config, no fetcher, no clock. That is what makes one stage
of the pipeline testable without the other five.

Two rules, in this order, because reversing them is the classic bug: the
`[GLOBAL_FILTER]` exclusions are applied to every item **before** any group is
considered, so a globally banned story cannot sneak in through a group that
happens to match it.

Contract: docs/memory-ai/behavior/news-search.md (stage 4)
"""

from __future__ import annotations

from .item import fold

__all__ = ["blocked", "group_matches", "select"]


def _hits(folded_title, terms):
    """True when any term appears in the already-folded title."""
    return any(fold(t) in folded_title for t in terms if t and t.strip())


def blocked(item, global_terms):
    """True when a `[GLOBAL_FILTER]` exclusion matches - the item is dropped.

    Nothing downstream sees it: not a group, not the report, not a notification.
    """
    if not global_terms:
        return False
    return _hits(fold(item.title), global_terms)


def group_matches(item, group):
    """True when the item belongs to this group.

    Any-of, then required, then excluded - the order the contract fixes. Plain
    terms are compared on the folded title so `Điện tử` matches a keyword typed
    `dien tu`; a `/regex/` is applied to the **original** title, because a regex
    author is entitled to write their own case rules.
    """
    folded = fold(item.title)

    if not (_hits(folded, group.terms)
            or any(rx.search(item.title) for rx in group.regexes)):
        return False
    if any(fold(t) not in folded for t in group.required if t and t.strip()):
        return False
    return not _hits(folded, group.excluded)


def select(items, groups, global_terms):
    """(item, [label, ...]) for every item that survives. Order is preserved.

    An item that matches nothing is dropped here rather than carried along with
    an empty label list: every later stage would have to check for it.
    Labels come back in the keyword file's own group order, which is the order
    the report shows its sections in.
    """
    selected = []
    for item in items:
        if blocked(item, global_terms):
            continue
        labels = [g.label for g in groups if group_matches(item, g)]
        if labels:
            selected.append((item, labels))
    return selected
