"""Collapse the same story onto one row, then order and cap each group.

Layer 3 - the second half of selection. Like `filter.py` it imports no config
and reads no clock: the weights, the per-source weights and `now` all arrive as
arguments. That is deliberate. `rank.py` may import `keywords`, `item` and plain
data types and nothing else (the layering table in
docs/memory-ai/architecture/module-layout.md), so the `source_id -> rank_weight`
map is built by `__main__.py` out of `feeds[]` and `search_templates[]` and
handed down.

Contract: docs/memory-ai/behavior/news-search.md (stages 5 and 6)
"""

from __future__ import annotations

from dataclasses import dataclass

from .item import dedup_key

__all__ = ["Story", "collapse", "score", "fresh_enough", "rank_groups"]

# Past this many sources, another copy of the same story says nothing new. The
# frequency term is (n - 1) / SATURATION_SPAN, clamped at 1.0.
SATURATION_SPAN = 3.0

# What a source with no `rank_weight` in config is worth. Neutral rather than
# zero: an unknown id is a config gap, not a reason to bury the story.
DEFAULT_SOURCE_WEIGHT = 1.0


@dataclass
class Story:
    """One story after duplicates collapsed - the unit everything later reports.

    `item` is the first copy seen and the one displayed; `published_at` is the
    *earliest* of every copy, which is not necessarily `item.published_at`. The
    two differ on purpose: the title and link people click come from one source,
    the timestamp is the best fact any source had.
    """

    item: object
    source_ids: tuple = ()
    labels: tuple = ()
    published_at: object = None
    score: float = 0.0


def collapse(pairs):
    """[(item, labels)] -> [Story], one per dedup key, in first-seen order.

    The survivor keeps the earliest `published_at`, the union of `source_id`s
    and the union of matched labels. The size of that source union is the
    cross-source frequency signal `score()` reads: a story that showed up on
    Hacker News *and* Lobsters *and* a search is, empirically, the story of the
    day.
    """
    by_key = {}
    for item, labels in pairs:
        key = dedup_key(item)
        story = by_key.get(key)

        if story is None:
            by_key[key] = Story(item=item, source_ids=(item.source_id,),
                                labels=tuple(labels),
                                published_at=item.published_at)
            continue

        if item.source_id not in story.source_ids:
            story.source_ids += (item.source_id,)
        story.labels += tuple(l for l in labels if l not in story.labels)
        if story.published_at is None or (
                item.published_at is not None
                and item.published_at < story.published_at):
            story.published_at = item.published_at

    return list(by_key.values())


def score(story, weights, source_weights, now):
    """The weighted sum: best source, how many sources carried it, how fresh.

    An unknown `published_at` gets a freshness term of 0, never a guess - "now"
    would put every dateless feed at the top of every group. A timestamp in the
    *future* is clamped to age 0 rather than trusted: `0.5 ** negative` is
    greater than 1, so one feed with a bad pubDate or a skewed clock would
    outrank every real story.
    """
    best_source = max(
        (source_weights.get(s, DEFAULT_SOURCE_WEIGHT) for s in story.source_ids),
        default=DEFAULT_SOURCE_WEIGHT)
    frequency = min(1.0, (len(story.source_ids) - 1) / SATURATION_SPAN)

    freshness = 0.0
    if story.published_at is not None:
        half_life = weights.get("freshness_half_life_hours") or 12.0
        age_hours = max(0.0, (now - story.published_at).total_seconds() / 3600.0)
        freshness = 0.5 ** (age_hours / half_life)

    return (weights.get("weight_source", 0.5) * best_source
            + weights.get("weight_frequency", 0.3) * frequency
            + weights.get("weight_freshness", 0.2) * freshness)


def fresh_enough(story, now, max_age_days):
    """Is this story inside the absolute age limit? `0` days switches it off.

    The floor `score()` cannot express. Freshness decays as
    `0.5 ** (age / half_life)` and reaches 0 after about two days, so past that
    point a three-day-old story and a three-year-old one are the same number -
    and a group short of fresh matches fills the rest of its cap from whatever
    archive a feed happens to ship. Measured on the shipped template
    2026-09-07: 12 of 68 shortlisted stories were over 30 days old, five of them
    Hugging Face posts taking half of `AI Repos`, the oldest 27,466 hours.

    **A story with no `published_at` is kept**, at every threshold. That is the
    same rule `score()` follows from the other end - a missing date is not
    evidence, and guessing "old" here would be as wrong as guessing "now"
    there. It is also load-bearing: the shipped `gh_trending` feed dates not one
    of its entries, so dropping the undated would empty its group entirely.
    """
    if max_age_days <= 0 or story.published_at is None:
        return True
    return (now - story.published_at).total_seconds() <= max_age_days * 86400.0


def rank_groups(stories, groups, weights, source_weights, now, default_cap=0,
                max_age_days=0):
    """{label: [Story, ...]} - each group sorted best first, then capped.

    Every group gets a key even when nothing matched it. An empty section is
    the signal that a keyword has gone quiet, and dropping it would hide exactly
    the thing worth noticing.

    The cap is the group's own `@n`, falling back to `default_cap`
    (`report.max_per_group`). `0` means unlimited in both.

    `max_age_days` is applied to the whole pool **before** any group is filled,
    so a group at its cap stays at its cap as long as fresh candidates remain
    below the line - the cut changes *which* stories fill a section, not how
    many, until a keyword genuinely has nothing recent.
    """
    stories = [s for s in stories if fresh_enough(s, now, max_age_days)]

    for story in stories:
        story.score = score(story, weights, source_weights, now)

    ranked = {}
    for group in groups:
        picked = sorted((s for s in stories if group.label in s.labels),
                        key=lambda s: s.score, reverse=True)
        cap = group.cap if group.cap is not None else default_cap
        ranked[group.label] = picked[:cap] if cap else picked
    return ranked
