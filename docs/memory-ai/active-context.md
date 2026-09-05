---
title: Active Context
updated: 2026-09-05
---

# Active Context

> What is being worked on right now. Read first every session; rewrite when the focus shifts. Transient - not a durable fact.

## Current focus

**v0.1.0 is released** (2026-09-05) - P0 Foundation is closed and published.
The next piece of work is **P1 Fetch**: getting real items out of the eight fixed
feeds and the keyword-built search feeds, which is the first phase that produces
something a human can look at.

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
- A second workflow, `test.yml`, now runs `tests/test_*.py` on push and pull
  request; `release.py --dry-run 0.1.0` was exercised against the real history.
- Caddy's published host port moved to `NEWS_RADAR_HTTP_PORT` (default `8088`)
  after 8080 turned out to be taken by ntfy on the homelab.
- **The predecessor stack was removed on 2026-09-05.** Six containers - `ntfy`,
  `rsshub`, `zenfeed-web`, `zenfeed`, `tunnel`, `apprise` - were still running
  from `compose/docker-compose.yml`, a file that had been deleted and was never
  in git. They carried the compose project name `news-radar`, so
  `docker compose ... down` would have swept them along with our Caddy. All six
  are gone; the volumes `ntfy-data` and `news-radar_caddy_data` were left in
  place. `8080` is free again, and the default stays `8088` by choice.
- **`Dockerfile`, `requirements.txt` and the `src/news_radar/` skeleton landed**
  (2026-09-05), unblocking P1. Only `__init__.py`, `__main__.py` and `config.py`
  were written - the stage modules are deliberately not stubbed, because an empty
  file claiming to be `fetch/http.py` reads as implemented when it is not.
- Removed the empty directories Docker had created under `config/` as
  bind-mount targets for that stack: `zenfeed.yaml/`, `cloudflared.yml/` and
  `apprise/newsradar.yml/`. Git never saw them - it does not track empty
  directories - so they never appeared in `git status`.
- `LICENSE` added: Apache-2.0, closing the decision `adr-0001` had left open.
- README restructured: badges, standard section order, no hardcoded deployment
  host, and no pointers into `docs/memory-ai` - the bank is working state for an
  assistant, not documentation to send a user of the project to read.
- `setup.py` now brings the stack up itself; `rule/changelog.md` added and
  `release.py` rewritten to promote a hand-written `Unreleased` section instead
  of generating one from commit subjects.
- **History was rewritten once** to strip a `Co-Authored-By` trailer from the
  root commit, which changed every hash and force-pushed all three branches. Any
  clone made before 2026-09-05 is on orphaned history and needs
  `git fetch && git reset --hard origin/<branch>`, not `git pull`.

## Next steps

1. **P1-1 HTTP client** - User-Agent from `cfg.user_agent()`, timeout, retry
   with backoff, per-hostname minimum interval. Reddit's 403 on an anonymous UA
   is the first thing to prove fixed. It lands in `fetch/http.py` and everything
   else in P1 goes through it.
2. **P1-2 and P1-3** - feed parsing via `feedparser`, then the fixed-feed reader
   producing normalised `NewsItem`s. Fold **P1-6** (HN Algolia returns JSON, not
   a feed) in here rather than leaving it last: it is a second format for the
   same reader, not a separate stage. **P1-5** (per-source failure isolation) is
   woven in from the start, not wrapped around afterwards.
3. **P1-4** - the search-feed generator, expanding each keyword group into the
   enabled search templates.
4. **Verify with `python -m news_radar --once`** - P1 is done when it prints N
   raw items from both the fixed feeds and the keyword-built searches.

## Active decisions

- **Clean-room from TrendRadar.** It is a reference to consult when stuck, never
  a source to copy from - it is GPL-3.0. `rule/reference-trendradar.md` says
  where to look by problem and what may not cross back.
- **Two runtime dependencies, total**: `pyyaml` and `feedparser`. HTTP, storage
  and templating come from the standard library. A third needs justifying in the
  changelog.
- **The changelog records technical changes only**, written by hand into
  `## Unreleased` in the same commit as the change. `release.py` reads no commit
  subjects. The rule is `rule/changelog.md`.
- **Both scripts stay stdlib-only** so they run on a bare checkout, before
  anything is installed.
- **Self-hosted, not GitHub Pages.** The crawl and the site both run on the
  homelab; `news.dtbao.org` is reached through the existing Cloudflare Tunnel.
- **Secrets live only in `docker/.env`.** `config.yaml` is committed as a
  template and a leaked copy must be harmless.
