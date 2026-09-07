---
title: Storage and Render Layer Contracts
category: interface
purpose: Every public signature of the store and render modules - what each writes, what the page is built from, and the row shape that travels between them.
status: active
updated: 2026-09-06
source: src/news_radar/store.py, src/news_radar/render.py, src/news_radar/__main__.py
confidence: confirmed
keywords: backup, restore, open_db, migration, schema version, user_version, start_run, finish_run, save, day_matches, run_matches, unreported, mark_reported, prune, to_db, from_db, local_tz, day_bounds, write, StoreError, SCHEMA_VERSION, seen set, retention, index.html, day snapshot
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
| `open_db(data_dir)` | `sqlite3.Connection` | Creates `data_dir`, connects to `news.db`, dispatches on `user_version`. `row_factory` is `sqlite3.Row` |
| `start_run(conn, started_at)` | `run_id: str` | Opens the `runs` row. Id is the UTC start as `%Y%m%dT%H%M%SZ`, with a `-2`, `-3`… suffix if that second is taken |
| `finish_run(conn, run_id, finished_at, items_fetched, items_matched, errors)` | `None` | Closes the row; `errors` is JSON-encoded as a list of pairs |
| `save(conn, run_id, ranked, now)` | `int` | `{label: [Story]}` in, number of `matches` rows written out |
| `day_matches(conn, start_utc, end_utc)` | `{label: [row]}` | Only labels that have rows. See the row shape below |
| `run_matches(conn, run_id)` | `{label: [row]}` | The same row shape for one run - what a notification is built from |
| `unreported(conn, dedup_keys, channel)` | `[dedup_key]` | The seen-set diff, in the caller's order. `[]` for an empty input |
| `mark_reported(conn, dedup_keys, channel, when)` | `None` | Idempotent - `INSERT OR IGNORE` |
| `unsummarised(conn, dedup_keys)` | `[dedup_key]` | Those with `ai_summary IS NULL`, in the caller's order. `""` counts as summarised - see [[ai-summary]] |
| `save_summaries(conn, summaries)` | `int` | `{dedup_key: text}` onto `items.ai_summary`. Writes `""` too: that is the record of having asked |
| `backup(conn, backup_dir, now, keep)` | `(path \| None, removed)` | One `news-<UTC date>.db` per day via `conn.backup()`. A second call the same day returns `(None, 0)`. `keep <= 0` writes nothing and creates no directory |
| `prune(conn, data_dir, retention_days, now)` | `(rows, files)` | `retention_days <= 0` deletes nothing and returns `(0, 0)`. The shipped `config.yaml` sets `90`; the fallback for an **absent** key stays `0` |
| `to_db(moment)` / `from_db(text)` | `str \| None` / `datetime \| None` | The one serialisation, both ways |

**`open_db()` understands four cases, and only two of them open the file.**

| `user_version` | What happens |
|----------------|--------------|
| `== SCHEMA_VERSION` | Opened |
| `0` | No file, or an empty one. The schema is created and the version stamped. Not an error - it is the first run |
| `> SCHEMA_VERSION` | `StoreError`. Another copy of this store is written by a newer build, and dropping columns it needs is not a recovery |
| `1` | **Migrated in place**: `ALTER TABLE items ADD COLUMN excerpt TEXT` and `ai_summary TEXT`, then the version is stamped. A v1 store is a homelab collecting since P4, and two nullable columns are not a reason to throw it away |
| anything in between | `StoreError`, naming both versions |

`SCHEMA_VERSION` is `2`, so the last row is again the empty set - `0 < v < 2`
holds for nothing once `1` has its own branch - and it exists so that the day it
becomes reachable is a loud one. Until v0.2.3 that case fell through every
branch and `open_db()` returned a connection to a store whose shape the build
did not match, which is how a query silently reads a column that means something
else now.

**Bumping `SCHEMA_VERSION` means writing the migration in a branch of its own**,
above the one that raises, in the same commit. `1 -> 2` is the worked example. The cycle survives a refusal either way: every caller is inside a
guard, so a refused store costs the page and the notifications, logs a
traceback, withholds the heartbeat ping, and alerts after two cycles.

### Tables

| Table | Columns | Purpose |
|-------|---------|---------|
| `items` | `dedup_key` PK, `title`, `url`, `canonical_url`, `first_seen_at`, `published_at`, `excerpt`, `ai_summary` | Every story ever shortlisted, one row per dedup key. `excerpt` is the feed's own description; `ai_summary` is NULL until asked |
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
4. **`excerpt` keeps the first non-empty** anyone carried. The second source to
   report a story may be the one with a description, and an empty string must
   never overwrite real text - the same shape as rule 2, for the same reason.

### The row both readers return

`day_matches()` and `run_matches()` are two callers of one private `_matches()`,
so the page and the senders can never disagree about the shape. One row per
`(story, group)` however many runs saw it - the **best** score in the slice wins,
because a story that got fresher during the day should not be ranked by the run
that noticed it first. Over a single run that is a no-op: the `matches` primary
key already allows one row per `(story, group, run)`.

The page shows a day and a message shows a run. That is the whole difference
between the two functions.

| Key | Type | Meaning |
|-----|------|---------|
| `dedup_key` | str | Its key, so the caller can diff against the seen-set |
| `title`, `url`, `canonical_url` | str | As stored |
| `score` | float | The best of the window |
| `published_at` | `datetime \| None` | Aware UTC, parsed back |
| `first_seen_at` | `datetime` | Aware UTC |
| `sources` | `tuple[str, ...]` | The accumulated source ids |
| `excerpt` | str | The feed's own description, stripped and capped. `""` when the source gave none |
| `ai_summary` | str | The model's sentence. `""` for both "not asked" and "asked, nothing useful" - the NULL/`""` distinction lives in SQL, not on the row |

## `render.py` - layer 5

Imports `html`, `zoneinfo`, `pathlib` and f-strings. No template engine: one
page does not earn a dependency.

| Signature | Returns | Notes |
|-----------|---------|-------|
| `local_tz(name)` | `tzinfo` | Never raises - see the fallback below |
| `day_bounds(now, tz)` | `(start_utc, end_utc)` | The local day containing `now`, half-open, expressed in UTC |
| `write(data_dir, labels, day_rows, meta, tz, threshold=5)` | `[Path, Path]` | Writes `index.html` and `days/<local date>.html`. Same body except `nav.days`, which is written for the depth of the file carrying it - see [[news-item]]. The AI sentences ride in the rows' own `ai_summary`, not as an argument |

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
`render.write` → `backup` → `prune` → `finish_run`, the whole sequence inside one
`try/except`, returning the **`run_id`** (or `None`) so the senders can read the
run back - see [[notify-channels]]. A locked database, a full disk or a read-only volume costs the
page, never the fetch: the cycle logs the traceback and still returns the
shortlist. **The page is rendered from `day_matches()`, never from the `ranked`
mapping still in memory** - that one choice is what makes a restart at noon
still publish what the morning found.

An empty `groups` list (an unusable keyword file) skips the render entirely and
leaves the previous page in place. A page with no sections at all reads as "no
news" rather than "the radar is broken", which is the wrong lie to tell.

See [[selection-layer]] for what produces `ranked`, and [[news-item]] for the
dedup key everything here is filed under.

## Backup and restore

`backup()` runs **immediately before `prune()`**, inside the same guard, and the
ordering is the point: if the copy cannot be written, the deletion below it never
runs either. No backup, no deletion.

Taken with SQLite's own `conn.backup()` rather than by copying the file - the
crawl service holds the connection open and a `-wal` may be mid-flush, so a
filesystem copy can produce a database that opens cleanly and is missing the last
write. The copy is written under `news-<date>.db.part` and renamed into place, so
an interrupted backup is never left looking like a good one.

**`ops.backup_dir` must never be under `storage.data_dir`.** Caddy serves that
directory to the public web, and a dated copy of the whole archive sitting in it
would be one Caddyfile line from being downloadable by anyone with the URL. The
shipped value is `backups`, bind-mounted to the crawl service only; `caddy` has
no mount for that path at all. `store.py` cannot enforce this - it does not know
what is being served - so it is a config rule, stated here and in the template.

**Restore is a manual procedure, deliberately.** A `--restore` flag would be more
code than the problem needs and would live on the one process that must not be
running while it happens:

```bash
docker compose -f docker/docker-compose.yml stop news-radar
cp backups/news-<date>.db output/news.db     # -wal / -shm are not restored
docker compose -f docker/docker-compose.yml start news-radar
```

The next cycle rewrites `index.html` from the restored store. Day snapshots under
`output/days/` are **not** in the backup: they are rendered output, and every one
of them is reproducible from the rows that are.
