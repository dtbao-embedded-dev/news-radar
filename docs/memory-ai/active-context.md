---
title: Active Context
updated: 2026-09-05
---

# Active Context

> What is being worked on right now. Read first every session; rewrite when the focus shifts. Transient - not a durable fact.

## Current focus

**P3 Store and render is done** (2026-09-05). `python -m news_radar --once`
writes `output/news.db` and a self-contained `output/index.html` plus
`output/days/<date>.html`, grouped by keyword group with a dark mode, a search
box and a link to every past day. A second `--once` kept **all 50 of the first
run's stories on the page**. That is the phase's definition of done.

The next piece of work is **P4 Notify**: the Telegram and Discord senders, the
new-only diff against the seen-set `store.py` already writes, and the backoff
both channels need. `store.unreported()` and `store.mark_reported()` exist,
are tested, and have no caller yet - P4 is the first one.

## Recent changes

- **P3 landed in six commits on `release/v0.1`** (2026-09-05): `store.py` (five
  tables migrated on `user_version`, `save`, `day_matches`, the seen-set,
  `prune`), `render.py` (`local_tz`, `day_bounds`, `write`), and the
  `_publish()` wiring in `__main__.py`.
- **The page is rendered from the store, never from the run in memory.** That
  one choice is what makes "history survives a restart" true. It was proven, not
  assumed: five stories scored higher in run 1 than in run 2 and the page
  carried run 1's score for all five.
- **The search templates were narrowed and it worked - at a cost.** `when:7d`
  and `search_by_date` make the freshness term fire (ten stories now clear the
  `0.40` source-only floor where none did), but Google News (vi) returned
  **16 items instead of 253** because the Vietnamese index has almost no recent
  embedded coverage. Kept deliberately; the detail is in `progress.md`.
- **Two departures from the design bank, both recorded in [[news-item]]**: the
  sources are a table rather than a JSON column on `items`, and
  `days/<date>.html` is rewritten every run rather than once at midnight.
- **`interface/storage-layer.md` is new**, and `news-item.md`,
  `crawl-cli.md`, `module-layout.md`, `delivery-phases.md` are restamped against
  the real modules. `news-item.md` carries no 🟡 markers any more.

Before this session: P2 landed the selection layer, P1 the whole fetch layer,
P0 the release tooling, the docker stack, the config loader and the design bank
- see `progress.md`.

## Next steps

1. **P4-1 Telegram sender** - bot API, the message length limit, HTML escaping.
2. **P4-2 Discord sender** - webhook, embed limits, the 2000-character body.
3. **P4-3 the new-only diff** - `store.unreported()` per channel; nothing new
   means nothing sent, and `mark_reported()` is written only after the chunk was
   accepted.
4. **P4-4 backoff** - 429 and `Retry-After` on both channels.
5. **Watch the page for a few days.** Retention is written but has never run
   against a window that had anything to drop - `retention_days` is `0` in the
   shipped config, so nothing prunes until someone sets it.

## Active decisions

- **The page is rendered from the store, not from `ranked`.** `day_matches()`
  returns the whole local day; rendering the in-memory shortlist would publish
  an afternoon that has forgotten its own morning. A `render.write(..., ranked)`
  anywhere is a bug, not a shortcut.
- **Layer 3 and layer 4 import no config and read no clock.** The weights, the
  `{source_id: rank_weight}` map, the data directory, the retention window and
  `now` are all arguments `__main__.py` builds. It is why nine of the eleven
  test files run with nothing installed.
- **Everything off a feed is escaped at the render boundary.** Titles, links and
  source ids all go through `html.escape`. A feed title is somebody else's text
  arriving unreviewed every thirty minutes.
- **The page needs no network to be read.** Inline CSS and JavaScript, no
  external stylesheet, script or image - `test_render.py` asserts it rather than
  trusting it.
- **Clean-room from TrendRadar.** It is a reference to consult when stuck, never
  a source to copy from - it is GPL-3.0. `rule/reference-trendradar.md` says
  where to look by problem and what may not cross back.
- **Two runtime dependencies, total**: `pyyaml` and `feedparser`. HTTP, storage
  and templating come from the standard library. A third needs justifying in the
  changelog. P3 held the line - the store is `sqlite3` and the page is
  f-strings. It is also why `render.local_tz()` falls back to the host offset
  instead of the project taking `tzdata` for one lookup.
- **One guard, not one per caller.** `feeds.read_source()` is the only place a
  source failure is caught; `_publish()` is the only place a storage or render
  failure is. A second guard anywhere is a bug.
- **The changelog records technical changes only**, written by hand into
  `## Unreleased` in the same commit as the change. One entry per change, not
  per commit: all of P3 is one `**crawl**` line, and the search-window fix is a
  `**config**` line of its own because it is a separate change.
- **Both scripts stay stdlib-only** so they run on a bare checkout, before
  anything is installed.
- **Self-hosted, not GitHub Pages.** The crawl and the site both run on the
  homelab; `news.dtbao.org` is reached through the existing Cloudflare Tunnel.
- **Secrets live only in `docker/.env`.** `config.yaml` is committed as a
  template and a leaked copy must be harmless.
