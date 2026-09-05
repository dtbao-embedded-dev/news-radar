---
title: Storage and Render Layer Contracts
category: interface
purpose: Every public signature of the store and render modules - what each writes, what the page is built from, and the row shape that travels between them.
status: active
updated: 2026-09-05
source: src/news_radar/store.py, src/news_radar/render.py, src/news_radar/__main__.py
confidence: confirmed
keywords: open_db, start_run, finish_run, save, day_matches, unreported, mark_reported, prune, to_db, from_db, local_tz, day_bounds, write, StoreError, SCHEMA_VERSION, seen set, retention, index.html, day snapshot
order: 7
---

# Storage and Render Layer Contracts

> Two modules, layers 4 and 5. `store.py` writes every shortlisted story into
> one SQLite file and answers "has this gone out yet?"; `render.py` turns a day
> of that store into one self-contained page. Neither imports `config`: the data
> directory, the retention window, the timezone name and every timestamp arrive
> as arguments that `__main__.py` builds, the same discipline layer 3 holds.

## `store.py` - layer 4

Imports `sqlite3`, `json`, `pathlib` and `item.dedup_key`. Nothing else.

| Signature | Returns | Notes |
|-----------|---------|-------|
| `open_db(data_dir)` | `sqlite3.Connection` | Creates `data_dir`, connects to `news.db`, migrates on `user_version`. `row_factory` is `sqlite3.Row` |
| `start_run(conn, started_at)` | `run_id: str` | Opens the `runs` row. Id is the UTC start as `%Y%m%dT%H%M%SZ`, with a `-2`, `-3`… suffix if that second is taken |
| `finish_run(conn, run_id, finished_at, items_fetched, items_matched, errors)` | `None` | Closes the row; `errors` is JSON-encoded as a list of pairs |
| `save(conn, run_id, ranked, now)` | `int` | `{label: [Story]}` in, number of `matches` rows written out |
| `day_matches(conn, start_utc, end_utc)` | `{label: [row]}` | Only labels that have rows. See the row shape below |
| `unreported(conn, dedup_keys, channel)` | `[dedup_key]` | The seen-set diff, in the caller's order. `[]` for an empty input |
| `mark_reported(conn, dedup_keys, channel, when)` | `None` | Idempotent - `INSERT OR IGNORE` |
| `prune(conn, data_dir, retention_days, now)` | `(rows, files)` | `retention_days <= 0` deletes nothing and returns `(0, 0)` |
| `to_db(moment)` / `from_db(text)` | `str \| None` / `datetime \| None` | The one serialisation, both ways |

`StoreError` is raised only when the file's `user_version` is **higher** than
`SCHEMA_VERSION`: the store migrates forward and refuses to downgrade. A missing
file is not an error - it is the first run.

### Tables

| Table | Columns | Purpose |
|-------|---------|---------|
| `items` | `dedup_key` PK, `title`, `url`, `canonical_url`, `first_seen_at`, `published_at` | Every story ever shortlisted, one row per dedup key |
| `item_sources` | `(dedup_key, source_id)` PK | Which sources carried it - accumulating, one row per pair |
| `matches` | `(dedup_key, group_name, run_id)` PK, `score` | Which groups it matched in a given run, and the score that run gave it |
| `reported` | `(dedup_key, channel)` PK, `reported_at` | The seen-set: what has already gone out, per channel |
| `runs` | `run_id` PK, `started_at`, `finished_at`, `items_fetched`, `items_matched`, `errors` | One row per crawl, for the heartbeat and for debugging a quiet day |

Timestamps are ISO-8601 **UTC** strings, every one carrying the same `+00:00`
suffix, so `<` and `>` in SQL mean what they say and no comparison has to go
through Python. Local time never reaches this module.

### The three re-sighting rules

A story found again tomorrow is the same row, not a second one, and `save()`
holds all three in one UPSERT:

1. **`first_seen_at` never moves.** It is the answer to "is this new?", which is
   the whole of P4's diff.
2. **`published_at` keeps the earliest non-null** anyone reported. A source that
   gives no timestamp must not erase one that did, so a `NULL` never wins.
3. **The source set accumulates**, because `item_sources` ignores a duplicate.

### The row `day_matches` returns

One row per `(story, group)` however many runs saw it - the **best** score any
run in the window gave it wins, because a story that got fresher during the day
should not be ranked by the run that noticed it first.

| Key | Type | Meaning |
|-----|------|---------|
| `dedup_key` | str | Its key, so the caller can diff against the seen-set |
| `title`, `url`, `canonical_url` | str | As stored |
| `score` | float | The best of the window |
| `published_at` | `datetime \| None` | Aware UTC, parsed back |
| `first_seen_at` | `datetime` | Aware UTC |
| `sources` | `tuple[str, ...]` | The accumulated source ids |

## `render.py` - layer 5

Imports `html`, `zoneinfo`, `pathlib` and f-strings. No template engine: one
page does not earn a dependency.

| Signature | Returns | Notes |
|-----------|---------|-------|
| `local_tz(name)` | `tzinfo` | Never raises - see the fallback below |
| `day_bounds(now, tz)` | `(start_utc, end_utc)` | The local day containing `now`, half-open, expressed in UTC |
| `write(data_dir, labels, day_rows, meta, tz, threshold=5)` | `[Path, Path]` | Writes `index.html` and `days/<local date>.html` with identical bodies |

`labels` fixes the group order **and** is what keeps an empty group on the page:
a keyword that has gone quiet looks identical to a keyword nobody wrote about,
and only one of those is worth knowing. `day_rows` is what `day_matches()`
returned; a label with no entry there renders its section with `no stories
today` rather than vanishing.

`meta` is read with `.get()` and understands `run_id`, `fetched`, `matched`,
`sources`, `errors` and `generated_at`; `generated_at` also decides which date
the snapshot is filed under.

### What the page is

- **Self-contained.** The CSS and the JavaScript are inline and there is not one
  external stylesheet, script or image. A radar whose report needs a CDN stops
  being readable exactly when the network is the thing you wanted to read about.
  `tests/test_render.py` asserts this rather than trusting it.
- **Escaped at the boundary.** Every title, link and source id goes through
  `html.escape(..., quote=True)` on the way in. A feed title is somebody else's
  text and it arrives unreviewed every thirty minutes.
- **Dark mode** through CSS custom properties: `prefers-color-scheme` by default,
  overridden by a `data-theme` attribute the toggle sets and `localStorage`
  remembers. A `localStorage` that throws (private mode) costs the memory, not
  the page.
- **A search box** that filters `<li>` on `textContent`, folding diacritics the
  same way `item.fold()` does - so a search typed `dien tu` finds `Điện tử`.
  A group whose every story is filtered out hides itself.
- **`report.rank_threshold`** marks the first N of each group with a `hot` class.

### The timezone fallback

`local_tz()` never raises. Windows ships no tz database, so
`ZoneInfo("Asia/Ho_Chi_Minh")` resolves in the Linux container and can fail on a
developer's host; pulling in `tzdata` for one lookup would break the
two-runtime-dependency rule. An unresolvable name falls back to the host's own
offset and logs one line per name per process. Vietnam has no DST, so the
fallback is exact there - a zone that *does* observe DST would need `tzdata`.

## What `__main__._publish()` wires

`open_db` → `start_run` → `save` → `local_tz` + `day_bounds` → `day_matches` →
`render.write` → `prune` → `finish_run`, the whole sequence inside one
`try/except`. A locked database, a full disk or a read-only volume costs the
page, never the fetch: the cycle logs the traceback and still returns the
shortlist. **The page is rendered from `day_matches()`, never from the `ranked`
mapping still in memory** - that one choice is what makes a restart at noon
still publish what the morning found.

An empty `groups` list (an unusable keyword file) skips the render entirely and
leaves the previous page in place. A page with no sections at all reads as "no
news" rather than "the radar is broken", which is the wrong lie to tell.

See [[selection-layer]] for what produces `ranked`, and [[news-item]] for the
dedup key everything here is filed under.
