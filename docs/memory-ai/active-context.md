---
title: Active Context
updated: 2026-09-04
---

# Active Context

> What is being worked on right now. Read first every session; rewrite when the focus shifts. Transient - not a durable fact.

## Current focus

P0 Foundation shipped on `release/v0.1`. The next piece of work is **P1 Fetch**:
getting real items out of the eight fixed feeds and the keyword-built search
feeds, which is the first phase that produces something a human can look at.

## Recent changes

- Memory bank filled out: architecture (phases, layout, deployment), data
  (sources, item shape), interface (config, CLIs, notification channels),
  behavior (the crawl algorithm), rule (release, setup, how to consult
  TrendRadar), plus `adr-0001` recording the clean-room decision.
- `config/config.yaml.example`, `config/frequency_words.txt`, the compose stack
  and the Caddyfile added; `.gitignore` now keeps the real config, `docker/.env`
  and `output/` out of the repository.
- `scripts/setup.py` and `scripts/release.py` added, with
  `tests/test_release.py`.
- Release CI switched from manual dispatch to a `v*` tag trigger, taking its
  notes from `CHANGELOG.md`.
- Caddy's published host port moved to `NEWS_RADAR_HTTP_PORT` (default `8088`)
  after 8080 turned out to be taken by ntfy on the homelab.

## Next steps

1. **Add the `Dockerfile` and the `src/news_radar/` package skeleton** - the
   compose stack cannot start its crawl service until this exists, so it blocks
   every later verification.
2. **P1-1 HTTP client** - User-Agent from config, timeout, retry with backoff,
   per-hostname minimum interval. Reddit's 403 on an anonymous UA is the first
   thing to prove fixed.
3. **P1-2 and P1-3** - feed parsing via `feedparser`, then the fixed-feed reader
   producing normalised `NewsItem`s with per-source failure isolation.
4. **P1-4** - the search-feed generator, including the JSON shape from HN Algolia.

## Active decisions

- **Clean-room from TrendRadar.** It is a reference to consult when stuck, never
  a source to copy from - it is GPL-3.0. `rule/reference-trendradar.md` says
  where to look by problem and what may not cross back.
- **Two runtime dependencies, total**: `pyyaml` and `feedparser`. HTTP, storage
  and templating come from the standard library. A third needs justifying in the
  changelog.
- **Both scripts stay stdlib-only** so they run on a bare checkout, before
  anything is installed.
- **Self-hosted, not GitHub Pages.** The crawl and the site both run on the
  homelab; `news.dtbao.org` is reached through the existing Cloudflare Tunnel.
- **Secrets live only in `docker/.env`.** `config.yaml` is committed as a
  template and a leaked copy must be harmless.
