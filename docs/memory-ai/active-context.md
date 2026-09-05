---
title: Active Context
updated: 2026-09-05
---

# Active Context

> What is being worked on right now. Read first every session; rewrite when the focus shifts. Transient - not a durable fact.

## Current focus

**P2 Filter and rank is done** (2026-09-05). `python -m news_radar --once` turns
**597 raw items into 209 matches, 205 stories after dedup, and 50 kept across 7
keyword groups**, printed group by group with a score and the sources that
carried each story. That is the phase's definition of done.

The next piece of work is **P3 Store and render**: putting that shortlist in
SQLite, keeping a seen-set so P4 can diff it, and writing `output/index.html`.
`crawl()` already returns the ranked mapping P3 needs.

## Recent changes

- **P2 landed in five commits on `release/v0.1`** (2026-09-05): `filter.py`
  (`blocked`, `group_matches`, `select`), `rank.py` (`Story`, `collapse`,
  `score`, `rank_groups`), and the `crawl()` wiring that builds the two plain
  dicts layer 3 needs and prints the shortlist.
- **Two new test files, both stdlib-only.** `test_filter.py` and `test_rank.py`
  need neither PyYAML nor feedparser, because `filter.py` and `rank.py` import
  no config and read no clock. Seven of the nine test files now run on a bare
  Windows checkout.
- **The scoring formula grew one rule the design did not have**: an item dated
  in the future is clamped to age `0`. `0.5 ** negative` is greater than 1, so
  a single bad `pubDate` would have topped every group it appeared in.
- **`interface/selection-layer.md` is new**, and `behavior/news-search.md`,
  `architecture/module-layout.md`, `architecture/delivery-phases.md` are
  restamped against the real modules.

Before this session: P1 landed the whole fetch layer; P0 the release tooling,
the docker stack, the config loader and the design bank - see `progress.md`.

## Next steps

1. **P3-1 SQLite store** - items, sources and a per-run log, schema migrated on
   open. The shape is in `data/news-item.md`, whose last two sections are still
   marked 🟡 for exactly this.
2. **P3-2 seen-set** - what has already been reported, keyed the way P4's diff
   will read it.
3. **P3-3 renderer** - one self-contained `output/index.html` grouped by keyword
   group, then P3-4's dark mode, search box and per-day history.
4. **Narrow the search queries to a recent window** - a `config.yaml` change,
   not code. Google News and HN Algolia answer relevance-first, so most search
   hits are months old and score `0` for freshness. Worth doing before the page
   exists, or the first published report will look stale.

## Active decisions

- **Layer 3 imports no config and reads no clock.** The weights, the
  `{source_id: rank_weight}` map and `now` are arguments `__main__.py` builds.
  It is why the selection tests run with nothing installed, and a `cfg` import
  inside `filter.py` or `rank.py` is a bug, not a shortcut.
- **Clean-room from TrendRadar.** It is a reference to consult when stuck, never
  a source to copy from - it is GPL-3.0. `rule/reference-trendradar.md` says
  where to look by problem and what may not cross back.
- **Two runtime dependencies, total**: `pyyaml` and `feedparser`. HTTP, storage
  and templating come from the standard library. A third needs justifying in the
  changelog. P1 and P2 both held the line - selection is pure stdlib.
- **One guard, not one per caller.** `feeds.read_source()` is the only place a
  source failure is caught; `search.py` calls it rather than repeating the
  try/except. A second guard anywhere is a bug.
- **The changelog records technical changes only**, written by hand into
  `## Unreleased` in the same commit as the change. One entry per change, not
  per commit: all of P2 is one `**crawl**` line.
- **Both scripts stay stdlib-only** so they run on a bare checkout, before
  anything is installed.
- **Self-hosted, not GitHub Pages.** The crawl and the site both run on the
  homelab; `news.dtbao.org` is reached through the existing Cloudflare Tunnel.
- **Secrets live only in `docker/.env`.** `config.yaml` is committed as a
  template and a leaked copy must be harmless.
