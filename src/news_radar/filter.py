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


def _hits(folded_text, terms):
    """True when any term appears in the already-folded text."""
    return any(fold(t) in folded_text for t in terms if t and t.strip())


def _haystack(item, excerpt):
    """What this item is matched against: its title, or title plus excerpt.

    Off by default, and per source rather than global, because the excerpt is a
    much looser signal than a headline. Measured on 2026-09-07 across twelve
    live sources: reading it for everything found 42% more matches and the
    extras were noise - `An Alien Mind` from Hacker News, `Kernel prepatch
    7.3-rc2` from LWN, stories that mention a keyword once in the body.

    One source needs it. The GitHub trending feed titles every entry
    `owner/repo` and puts the description in the excerpt, so title-only
    matching passed 1 of 18 entries; with the excerpt, 10.
    """
    if not excerpt:
        return item.title
    return "{}\n{}".format(item.title, item.excerpt or "")


def blocked(item, global_terms, excerpt=False):
    """True when a `[GLOBAL_FILTER]` exclusion matches - the item is dropped.

    Nothing downstream sees it: not a group, not the report, not a notification.

    `excerpt` widens this in step with `group_matches()` and must never be set
    independently of it: a source whose *matching* reads the excerpt but whose
    *exclusions* do not is one that cannot filter back out the noise the wider
    reading just let in.
    """
    if not global_terms:
        return False
    return _hits(fold(_haystack(item, excerpt)), global_terms)


def group_matches(item, group, excerpt=False):
    """True when the item belongs to this group.

    Any-of, then required, then excluded - the order the contract fixes. Plain
    terms are compared on the folded title so `Điện tử` matches a keyword typed
    `dien tu`; a `/regex/` is applied to the **original** text, because a regex
    author is entitled to write their own case rules.

    `excerpt` extends every one of those three rules to the item's excerpt as
    well - see `_haystack()` for why it is off unless a source asks. It widens
    `required` and `excluded` too, deliberately: a `+term` that would have to
    appear in a `owner/repo` title is unsatisfiable, and an `!term` that cannot
    see the text the match came from cannot undo it.
    """
    raw = _haystack(item, excerpt)
    folded = fold(raw)

    if not (_hits(folded, group.terms)
            or any(rx.search(raw) for rx in group.regexes)):
        return False
    if any(fold(t) not in folded for t in group.required if t and t.strip()):
        return False
    return not _hits(folded, group.excluded)


def select(items, groups, global_terms, excerpt_sources=()):
    """(item, [label, ...]) for every item that survives. Order is preserved.

    An item that matches nothing is dropped here rather than carried along with
    an empty label list: every later stage would have to check for it.
    Labels come back in the keyword file's own group order, which is the order
    the report shows its sections in.

    `excerpt_sources` holds the `source_id`s whose excerpt counts as matchable
    text - a set of ids rather than the config itself, because layer 3 does not
    import `config`. `__main__._excerpt_sources()` builds it. Empty, which is
    the default and what every existing caller passes, is the behaviour that
    shipped: title only, for everything.
    """
    excerpt_sources = frozenset(excerpt_sources or ())
    selected = []
    for item in items:
        excerpt = item.source_id in excerpt_sources
        if blocked(item, global_terms, excerpt):
            continue
        labels = [g.label for g in groups if group_matches(item, g, excerpt)]
        if labels:
            selected.append((item, labels))
    return selected
