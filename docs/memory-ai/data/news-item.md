---
title: News Item, Dedup Key and Output Layout
category: data
purpose: The shape every story is normalised into, how duplicates collapse, and what lands on disk under output/.
status: active
updated: 2026-09-05
source: src/news_radar/item.py, src/news_radar/fetch/feeds.py, src/news_radar/store.py, src/news_radar/render.py
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

One file, `output/news.db`. Schema described as shape, not DDL - the exact
signatures are in [[storage-layer]].

| Table | Columns | Purpose |
|-------|---------|---------|
| `items` | `dedup_key` (PK), `title`, `url`, `canonical_url`, `first_seen_at`, `published_at` | Every story ever shortlisted, one row per dedup key |
| `item_sources` | `(dedup_key, source_id)` (PK) | Which sources carried it - one row per pair, accumulating |
| `matches` | `(dedup_key, group_name, run_id)` (PK), `score` | Which groups an item matched in a given run, and the score it got |
| `reported` | `(dedup_key, channel)` (PK), `reported_at` | The seen-set: what has already gone out to Telegram or Discord |
| `runs` | `run_id` (PK), `started_at`, `finished_at`, `items_fetched`, `items_matched`, `errors` (JSON) | One row per crawl, for the heartbeat and for debugging a quiet day |

**The sources are a table, not a JSON column on `items`.** The design called for
a `sources` JSON array; a table earns its place because the union of sources is
then an `INSERT OR IGNORE` away, instead of a read-modify-write of the row on
every re-sighting. It also reads back as one `group_concat` in the day query.

`reported` is keyed per channel on purpose: adding Discord later must not
retroactively count stories already pushed to Telegram as "sent".

Schema version lives in SQLite's `user_version` pragma; `store.py` migrates
forward on open and never migrates backward - a file written by a **higher**
version raises `StoreError` rather than being downgraded.

Every timestamp is an ISO-8601 UTC string carrying the same `+00:00` suffix, so
`<` and `>` in SQL mean what they say. Local time is applied only at render time.

### The three re-sighting rules

A story found again tomorrow is the same row, not a second one:

1. `first_seen_at` never moves once set - it is the answer to "is this new?".
2. `published_at` keeps the **earliest** non-null anyone reported; a source that
   gives no timestamp never erases one that did.
3. The source set accumulates.

## Output layout

```
output/
├── index.html          # current report - what Caddy serves at /
├── news.db             # SQLite store above
└── days/
    └── 2026-09-04.html # one snapshot per day, linked from index.html
```

- `index.html` is rewritten every run; it is never appended to.
- `days/<date>.html` is written **every run**, with the identical body, under the
  current local date. A past day is still never touched - the filename moves with
  the date - and there is no day-rollover branch to get wrong. The design called
  for writing it once at midnight; this has the same effect with less to break.
- Both files are self-contained: inline CSS and JavaScript, no external
  stylesheet, script or image. A report that needs a CDN stops being readable
  exactly when the network is the thing you wanted to read about.
- Retention (`storage.retention_days`, default 0 = keep everything) prunes
  `days/` files and `items` rows older than the window in the same pass.

Everything under `output/` is gitignored. It is derived data: deleting the whole
directory costs the archive, not the configuration.
