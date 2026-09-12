---
title: News Item, Dedup Key and Output Layout
category: data
purpose: The shape every story is normalised into, how duplicates collapse, and what lands on disk under output/.
status: active
updated: 2026-09-12
source: src/news_radar/item.py, src/news_radar/fetch/feeds.py, src/news_radar/store.py, src/news_radar/render.py
confidence: confirmed
keywords: NewsItem, dedup key, title_key, key_for_title, canonical url, schema version 3, migration chain, excerpt, EXCERPT_MAX, ai_summary, gist, sqlite schema, news.db, output layout, index.html, seen set, snapshot, page layout, rail, jump nav, hidden, filter, theme toggle
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
| `canonical_url` | str | yes | `url` after normalisation (see below). Stored and displayed; **not** the dedup input any more |
| `source_id` | str | yes | `id` of the fixed feed or search template it came from |
| `external_id` | str | yes | The source's own id (`guid`, `entry/id`, `objectID`); falls back to `canonical_url` |
| `published_at` | datetime \| None | no | Source timestamp, converted to UTC. `None` means the source gave none - never substitute "now" |
| `fetched_at` | datetime | yes | When this run retrieved it, UTC |
| `keyword_group` | str \| None | no | For a search-feed item: the group whose term produced the query |
| `excerpt` | str | no | The feed's own `<description>` / Atom `summary` or `content` (longest wins), HTML stripped and cut to `EXCERPT_MAX` (600). `""` when the source carried none. What the AI summary is written from - see [[ai-summary]] |

Invariants:

- `title` is never empty; an item without a title is dropped at parse time.
- `excerpt` is never `None` and never markup; an empty one is never a reason
  to drop a story, and it is not part of the dedup key.
- `title` is stable across runs for the same story, or dedup silently stops
  working. `canonical_url` is **not** part of identity any more - it is stored
  and displayed, nothing else.
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

The **headline is the identity**, and the URL is not. 🟢

```
dedup_key = sha1("t:" + title_key(title))
```

`title_key()` folds case and diacritics, drops a trailing `- Publisher` /
`| Publisher` byline when at least 5 words are left after it, then removes
punctuation and collapses whitespace. Punctuation goes here and not in `fold()`,
which keeps it so a keyword typed `ESP32-S3` still matches; identity wants the
opposite, because two sources disagreeing only about a colon carry one story.

`key_for_title(title)` is the same digest addressable without a `NewsItem` -
`store.open_db()` needs it to rekey a row it is migrating.

**Why not the URL.** It looks like the stronger key and is not one: Google News
answers the same article with a different opaque
`news.google.com/rss/articles/CBMi...` redirect on every query, so one story was
stored and sent under as many as **nine** keys. Measured on the live store
2026-09-12: **121 of 1269 items (9.6%) were duplicates of another row**, across
84 groups, and no group mixed two different stories. The headline key also
collapses what no URL rule could - the same piece from `cnx-software.com` and
from Google News' copy of it, or a Bloomberg story on Hacker News beside the one
carrying its byline. 🟢

Collapsing rule: the surviving record keeps the **earliest** `published_at` and
accumulates the set of `source_id`s that carried it. That set size is the
cross-source frequency term the ranking uses - see [[news-search]].

Two deliberate limits:

- **Exact match only.** Two outlets writing genuinely different headlines about
  one event stay two stories. Similarity clustering cannot be a hash and needs a
  threshold nobody has tuned; the `ponytail:` note in `item.dedup_key()` records
  it. 🟢
- **A byte-identical normalised headline is one story, always.** Two different
  articles sharing one would merge. None was found in those 1269 items, and real
  recurring columns carry a date or a version in the title
  (`Kernel prepatch 7.3-rc2`). 🟡

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

Schema version lives in SQLite's `user_version` pragma and is **3**. `store.py`
migrates forward on open and never backward - a file written by a **higher**
version raises `StoreError` rather than being downgraded, and so does one at a
version with no step to reach the current one.

Migrations run **as a chain**, not as a jump: a v1 store runs the v1→v2 step and
then the v2→v3 one. Jumping straight to the current number is how a store gets
stamped as migrated while a step it needed was skipped. 🟢

| Step | What it does |
|------|--------------|
| v1 → v2 | Adds the nullable `excerpt` and `ai_summary` columns to `items`. Nothing is rewritten. |
| v2 → v3 | Re-seeds `reported` with each already-sent story's **new** headline key, because v0.2.10 moved `dedup_key` off the URL. Adds rows only; old keys stay and age out with `retention_days`. |

The v2→v3 step rewrites only `reported` on purpose. Rekeying `items`, `matches`
and `item_sources` would have to merge rows that now collapse onto one key; the
ones left behind cost nothing. What must be exact is the seen-set, because
without it the first cycle after the upgrade re-sends a whole local day - one
message per story. Verified against a copy of the production store: 1241
already-sent stories, 0 re-sent. 🟢

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
- `days/<date>.html` is written **every run** under the current local date. A past
  day is still never touched - the filename moves with the date - and there is no
  day-rollover branch to get wrong. The design called for writing it once at
  midnight; this has the same effect with less to break.
- The snapshot carries the same page as `index.html` **except for `nav.days`**,
  which is written for the depth of the file carrying it: `days/<date>.html` from
  the root, a bare `<date>.html` from inside `days/`. The two files were once
  byte-identical, and that is precisely what made every day link on a day page a
  404 - a relative href resolves against the file carrying it, so the snapshot
  was asking for `/days/days/<date>.html`. `render._day_nav()` takes the prefix
  as an argument and `write()` renders the page once per destination.
- Both files are self-contained: inline CSS and JavaScript, no external
  stylesheet, script or image. A report that needs a CDN stops being readable
  exactly when the network is the thing you wanted to read about.
- Retention (`storage.retention_days`, default 0 = keep everything) prunes
  `days/` files and `items` rows older than the window in the same pass.

Everything under `output/` is gitignored. It is derived data: deleting the whole
directory costs the archive, not the configuration.

### What the page shows

The page is a sticky left rail beside one column of stories, inside a container
that is 80% of the viewport (92% below 900px). The rail carries the run's own
numbers, the filter, every group with its count, and the day list; `main` carries
the optional AI summary, then one `<section class="group">` per label in order.

| Element | Carries |
|---------|---------|
| `aside .stat` | `kept today`, `matched`, `fetched`, `sources`, `failed` - `failed` turns red only when it is non-zero |
| `#q` | the filter; matches on the diacritic-folded text of each `li.story` |
| `#theme` | the light/dark toggle, remembered in `localStorage` under `news-radar-theme` |
| `nav.jump` | one link per group to `#g-<slug>`, with its count; an empty group is dimmed, never dropped |
| `nav.days` | one link per snapshot on disk, newest first, today's included |
| `li.story` | the title and the timestamp on one baseline (two grid cells), and - when the story has one - `p.gist`, the AI sentence, on a second row spanning both columns. The title is `target="_blank"` + `rel="noopener noreferrer"` |

**Story links open in a new tab, internal links do not.** A story leads off this
site and the report is what the reader came back to, so `li.story a` carries
`target="_blank"`; `rel="noopener noreferrer"` is the half of that pair that
stops the opened page reaching back through `window.opener`, and neither is
useful alone. `nav.jump` and `nav.days` move around this same report and stay in
the tab - `tests/test_render.py` asserts both halves of that split.

**The score and the source ids are deliberately not on the page.** Both are still
in the store - `matches.score` is what ordered the list, `item_sources` still
records who carried each story - but a reader cannot act on `0.74`, and asked
what it meant. The first `report.rank_threshold` of each group keep the
`story hot` class; all it does now is set the title in a heavier weight.

Two consequences worth knowing before changing this:

- **The filter now matches titles only.** The source ids used to be in the DOM,
  so typing `lobsters` filtered by source. That is gone with them.
- **`[hidden] { display: none !important; }` is load-bearing.** `li.story` is a
  grid, and an author `display` beats the browser's own `[hidden]` rule - without
  the `!important` the filter hides nothing at all. `tests/test_render.py`
  asserts the rule is on the page.
