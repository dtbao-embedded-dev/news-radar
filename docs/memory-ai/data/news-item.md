---
title: News Item, Dedup Key and Output Layout
category: data
purpose: The shape every story is normalised into, how duplicates collapse, and what lands on disk under output/.
status: active
updated: 2026-09-05
source: src/news_radar/item.py, src/news_radar/fetch/feeds.py
confidence: confirmed
keywords: NewsItem, dedup key, canonical url, sqlite schema, news.db, output layout, index.html, seen set, snapshot
order: 2
---

# News Item, Dedup Key and Output Layout

> One flat record per story, one dedup key that collapses the same story arriving
> from several sources, one SQLite file and one HTML page under `output/`.

## NewsItem

Produced by `fetch/`, consumed by everything downstream. Immutable once built:
`filter.py` and `rank.py` attach their results to a separate wrapper rather than
mutating the item.

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `title` | str | yes | Headline, HTML stripped, whitespace collapsed |
| `url` | str | yes | Story link as published by the source |
| `canonical_url` | str | yes | `url` after normalisation (see below) - the dedup input |
| `source_id` | str | yes | `id` of the fixed feed or search template it came from |
| `external_id` | str | yes | The source's own id (`guid`, `entry/id`, `objectID`); falls back to `canonical_url` |
| `published_at` | datetime \| None | no | Source timestamp, converted to UTC. `None` means the source gave none - never substitute "now" |
| `fetched_at` | datetime | yes | When this run retrieved it, UTC |
| `keyword_group` | str \| None | no | For a search-feed item: the group whose term produced the query |

Invariants:

- `title` is never empty; an item without a title is dropped at parse time.
- `canonical_url` is stable across runs for the same story, or dedup silently stops working.
- All datetimes are timezone-aware UTC in memory and stored as UTC in SQLite.
  Local time (`TZ`, default `Asia/Ho_Chi_Minh`) is applied only at render time.

## URL canonicalisation

Applied in this order to produce `canonical_url`:

1. Lowercase the scheme and host; drop a leading `www.`.
2. Force `https`.
3. Drop tracking parameters: everything starting `utm_`, plus `fbclid`, `gclid`,
   `ref`, `ref_src`, `spm`, `s_cid`.
4. Drop the fragment.
5. Strip a trailing `/` unless the path is exactly `/`.
6. Leave every other query parameter intact - some sites carry the article id there.

## Dedup key

```
dedup_key = sha1(canonical_url)                       when the URL survives step 6 non-empty
          = sha1("t:" + normalised_title)             when the item has no usable URL
```

`normalised_title` is the title lowercased, diacritics folded, punctuation
removed, whitespace collapsed. The title fallback exists because aggregator items
sometimes carry only a permalink to the aggregator itself.

Collapsing rule: the surviving record keeps the **earliest** `published_at` and
accumulates the set of `source_id`s that carried it. That set size is the
cross-source frequency term the ranking uses - see [[news-search]].

Deliberate limit: the same story published under two different URLs (a syndicated
copy, an AMP variant) does **not** collapse. Title-similarity clustering is not
implemented; it would need a threshold nobody has tuned yet.

## SQLite store

> 🟡 `inferred` - this section and the next describe P3. `store.py` and
> `render.py` do not exist yet; everything above them is confirmed against
> `src/news_radar/item.py`.

One file, `output/news.db`. Schema described as shape, not DDL.

| Table | Columns | Purpose |
|-------|---------|---------|
| `items` | `dedup_key` (PK), `title`, `canonical_url`, `url`, `first_seen_at`, `published_at`, `sources` (JSON array of source ids) | Every story ever seen, one row per dedup key |
| `matches` | `dedup_key`, `group_name`, `score`, `run_id` | Which groups an item matched in a given run, and the score it got |
| `reported` | `dedup_key`, `channel`, `reported_at` | The seen-set: what has already gone out to Telegram or Discord |
| `runs` | `run_id` (PK), `started_at`, `finished_at`, `items_fetched`, `items_matched`, `errors` (JSON) | One row per crawl, for the heartbeat and for debugging a quiet day |

`reported` is keyed per channel on purpose: adding Discord later must not
retroactively count stories already pushed to Telegram as "sent".

Schema version lives in SQLite's `user_version` pragma; `store.py` migrates
forward on open and never migrates backward.

## Output layout

```
output/
├── index.html          # current report - what Caddy serves at /
├── news.db             # SQLite store above
└── days/
    └── 2026-09-04.html # one immutable snapshot per day, linked from index.html
```

- `index.html` is rewritten every run; it is never appended to.
- `days/<date>.html` is written once when a day rolls over and is not touched
  again, so a stale render can never rewrite history.
- Retention (`storage.retention_days`, default 0 = keep everything) prunes
  `days/` files and `items` rows older than the window in the same pass.

Everything under `output/` is gitignored. It is derived data: deleting the whole
directory costs the archive, not the configuration.
