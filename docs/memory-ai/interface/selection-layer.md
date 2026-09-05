---
title: Selection Layer Contracts
category: interface
purpose: Every public signature of the filter and rank modules - what each returns, what it never reads, and the plain dicts the caller has to build for it.
status: active
updated: 2026-09-05
source: src/news_radar/filter.py, src/news_radar/rank.py, src/news_radar/__main__.py
confidence: confirmed
keywords: blocked, group_matches, select, Story, collapse, score, rank_groups, source_weights, weights, default_cap, SATURATION_SPAN, DEFAULT_SOURCE_WEIGHT, global filter, cap
order: 6
---

# Selection Layer Contracts

> Two modules, layer 3. `filter.py` decides what gets through and which groups
> it belongs to; `rank.py` collapses duplicates and orders each group. Neither
> imports `config` and neither reads a clock: the weights, the per-source
> weights and `now` all arrive as arguments, which is what lets one stage be
> tested without the other five.

## `filter.py` - what gets through

| Signature | Returns |
|-----------|---------|
| `blocked(item, global_terms)` | `True` when a `[GLOBAL_FILTER]` exclusion matches the folded title. An empty `global_terms` blocks nothing |
| `group_matches(item, group)` | `True` when the item belongs to this `KeywordGroup`: any-of, then required, then excluded |
| `select(items, groups, global_terms)` | `[(NewsItem, [label, ...])]` - input order preserved. Items that are blocked, or that match no group, are **dropped** rather than carried with an empty label list |

Plain terms and `+`/`!` terms are compared on `fold(item.title)`; a `/regex/` is
run with `re.search` against the **original** title. Labels come back in the
keyword file's own group order, which is the order the report renders sections
in.

## `rank.py` - collapse, score, cap

| Signature | Returns |
|-----------|---------|
| `Story` | Mutable dataclass: `item`, `source_ids` (tuple), `labels` (tuple), `published_at`, `score=0.0` |
| `collapse(pairs)` | `[Story]`, one per `dedup_key()`, in first-seen order |
| `score(story, weights, source_weights, now)` | The weighted sum as a float. Does not mutate the story |
| `rank_groups(stories, groups, weights, source_weights, now, default_cap=0)` | `{label: [Story, ...]}` - sorted best first, then capped. **Writes `story.score` back** onto every story it is given |

`Story.item` is the first copy seen and the one displayed; `Story.published_at`
is the *earliest* of every copy and is not necessarily `item.published_at`. The
two differ on purpose - the link people click comes from one source, the
timestamp is the best fact any source had.

Every group in `groups` gets a key in the returned mapping, **including one that
matched nothing**. An empty section is how a keyword that has gone quiet becomes
visible; dropping it would hide exactly the thing worth noticing.

### The two dicts the caller builds

| Argument | Shape | Built from |
|----------|-------|------------|
| `weights` | `{"weight_source", "weight_frequency", "weight_freshness", "freshness_half_life_hours"}` | `cfg.get("rank")` |
| `source_weights` | `{source_id: rank_weight}` | `feeds[]` + `search_templates[]`, **enabled or not** |
| `default_cap` | int, `0` = unlimited | `report.max_per_group` |

`__main__._source_weights(cfg)` builds the second one. It lives there rather
than in `rank.py` because the layering table in [[module-layout]] gives layer 3
`keywords`, `item` and plain data types and nothing else - reading `cfg` inside
`rank.py` would be the back edge that makes the pipeline untestable a stage at a
time. Disabled entries are included on purpose: an item is scored by where it
came from, and a source switched off mid-cycle still carries the weight the
operator gave it. An id absent from the map scores `DEFAULT_SOURCE_WEIGHT`
(`1.0`) - a config gap is not a reason to bury a story.

### Constants

| Name | Value | Meaning |
|------|-------|---------|
| `SATURATION_SPAN` | `3.0` | The frequency term is `min(1.0, (n_sources - 1) / 3)`, so it saturates at four sources |
| `DEFAULT_SOURCE_WEIGHT` | `1.0` | What a source with no `rank_weight` in config is worth |

The scoring formula itself, and the two timestamp rules it enforces (unknown
scores `0`, future is clamped to age `0`), are in [[news-search]] stage 6.
