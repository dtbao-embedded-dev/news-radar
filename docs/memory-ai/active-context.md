---
title: Active Context
updated: 2026-09-05
---

# Active Context

> What is being worked on right now. Read first every session; rewrite when the focus shifts. Transient - not a durable fact.

## Current focus

**P1 Fetch is done** (2026-09-05). `python -m news_radar --once` pulls **597 raw
items** out of the eight fixed feeds and the fourteen keyword-built searches, in
one container run, exit 0.

The next piece of work is **P2 Filter and rank**: turning those 597 raw items
into the grouped, deduped, ranked shortlist a human would actually read. P2-1
(the keyword-file parser) is already done - it landed in P1 because the search
generator needed each group's primary term.

## Recent changes

- **P1 landed in seven commits on `release/v0.1`** (2026-09-05):
  `item.py` (the NewsItem shape, URL canonicalisation, dedup key, diacritic
  folding), `keywords.py` (the whole group syntax), `fetch/http.py` (User-Agent,
  timeout, retry, per-host throttle), `fetch/feeds.py` (RSS/Atom/Algolia JSON
  into items, the fixed-feed reader, the single failure guard),
  `fetch/search.py` (primary term x template into queries), and the `crawl()`
  wiring that counts what came back.
- **Five new test files, all offline.** `test_item`, `test_keywords` and
  `test_http` are stdlib-only; `test_feeds` and `test_search` read
  `tests/fixtures/`, one body per edge case the design predicted. Nothing in the
  suite touches the network, so CI stays green without egress.
- **`item.py` is a module the bank's tree did not have.** `NewsItem` is produced
  by `fetch/` and read by every later stage, and `data/news-item.md` makes
  `canonical_url` a required field - so canonicalisation and the dedup key are
  P1 work, not P2. `architecture/module-layout.md` now shows it.
- Bank restamped: `module-layout`, `delivery-phases`, `crawl-cli`,
  `news-item`, `news-sources` and `news-search` are `confirmed` against real
  code, and `interface/fetch-layer.md` is new.

Before this session, in P0: the release tooling, the docker stack, the config
loader and the design bank - see `progress.md`.

## Next steps

1. **P2-2 match engine** - decide which groups an item belongs to, using
   `item.fold()` so `Điện tử` matches a keyword typed `dien tu`. `/regex/` runs
   against the **original** title, not the folded one.
2. **P2-3 global filter** applied before grouping - one `!` hit from
   `[GLOBAL_FILTER]` drops the item entirely and no group sees it.
3. **P2-4 dedup** - `item.dedup_key()` already exists; P2 collapses on it,
   keeping the earliest `published_at` and the union of `source_id`s.
4. **P2-5 and P2-6** - the weighted score from `rank.*` in config, then the
   group's `@n` cap.
5. **Verify with `python -m news_radar --once`** - P2 is done when the same
   command prints grouped, deduped, ranked matches instead of 597 raw items.

## Active decisions

- **Clean-room from TrendRadar.** It is a reference to consult when stuck, never
  a source to copy from - it is GPL-3.0. `rule/reference-trendradar.md` says
  where to look by problem and what may not cross back.
- **Two runtime dependencies, total**: `pyyaml` and `feedparser`. HTTP, storage
  and templating come from the standard library. A third needs justifying in the
  changelog. P1 held the line - the transport is `urllib.request`.
- **One guard, not one per caller.** `feeds.read_source()` is the only place a
  source failure is caught; `search.py` calls it rather than repeating the
  try/except. A second guard anywhere is a bug.
- **The changelog records technical changes only**, written by hand into
  `## Unreleased` in the same commit as the change. One entry per change, not
  per commit: all of P1 is one `**crawl**` line.
- **Both scripts stay stdlib-only** so they run on a bare checkout, before
  anything is installed.
- **Self-hosted, not GitHub Pages.** The crawl and the site both run on the
  homelab; `news.dtbao.org` is reached through the existing Cloudflare Tunnel.
- **Secrets live only in `docker/.env`.** `config.yaml` is committed as a
  template and a leaked copy must be harmless.
