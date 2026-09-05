---
title: Progress
updated: 2026-09-05
---

# Progress

> Current delivery state - what works, what's left, known issues. Update at every checkpoint (feature shipped, milestone, direction change).

## What works

**P0 Foundation is complete.** See `architecture/delivery-phases.md` for the
phase map and the finished-product definition all of it serves.

- **The design bank is complete enough to build from.** Twelve durable docs plus
  one ADR cover the target architecture, the sources and their exact URLs, the
  item shape and dedup rule, every config key, the keyword-file syntax, the
  notification contracts, the crawl algorithm with its known edge cases, and the
  release and setup procedures.
- **`python scripts/setup.py` works on Windows and Linux.** Verified on this
  machine (Python 3.12, Docker Compose v2): it enforces the Python 3.11+ floor
  and the presence of Compose v2, creates
  `config/config.yaml` and `docker/.env` from their templates without ever
  overwriting an existing file, prompts for missing secrets while preserving the
  `.env` comments, and exits non-zero while a required secret is blank.
  `--dry-run`, `--check`, `--force` and `--non-interactive` all behave as
  documented.
- **`python scripts/release.py <version>` works.** `--dry-run 0.1.0` prints the
  changelog it would write, built from the real commit history, and the exact git
  chain: commit on `release/*`, merge into `developing`, merge into `main`, tag,
  return, push. `python tests/test_release.py` passes with plain asserts and no
  test framework.
- **CI publishes a release from a tag.** `.github/workflows/release.yml` triggers
  on `v*`, cuts the version's section out of `CHANGELOG.md` using `release.py`'s
  own extractor, and falls back to GitHub-generated notes when there is no
  section. Both paths were exercised locally against the real workflow code.
- **CI runs the checks on every push and pull request.**
  `.github/workflows/test.yml` runs every `tests/test_*.py` on Python 3.12 with
  no install step. Verified locally by running the same loop, and by proving a
  failing check aborts it instead of passing silently.
- **The docker stack is defined and Caddy actually runs.** Verified by starting
  it: Caddy serves `output/` with the `Cache-Control` headers from our Caddyfile.

## What's left

Everything the product actually does. The application layer is **specified but
not written** - `src/news_radar/` does not exist yet.

- **P1 Fetch** - HTTP client with a real User-Agent and per-host throttling, feed
  parsing, the fixed-feed reader, the keyword-driven search-feed generator, and
  per-source failure isolation.
- **P2 Filter and rank** - keyword-file parser, the match engine with diacritic
  folding, dedup, and the weighted ranking.
- **P3 Store and render** - SQLite store, the seen-set, and `output/index.html`.
- **P4 Notify** - Telegram and Discord senders, the new-only diff, and backoff.
- **P5 Deploy** - the `Dockerfile`, the schedule loop, and the Cloudflare Tunnel
  route for `news.dtbao.org`.
- **P6 Ops** - retention, heartbeat, failure alerting.

## Known issues

- **No `LICENSE` file.** news-radar is a clean-room reimplementation precisely so
  it is free to pick one (`adr-0001`), but nobody has picked it yet. Decide before
  the repository is made public.
- **The `news-radar` compose service cannot start.** It builds from a `Dockerfile`
  that lands in P5. Until then only `docker compose ... up -d caddy` works, and
  the compose file says so.
- **Host port 8080 is taken by ntfy on this homelab.** Caddy is published on
  `NEWS_RADAR_HTTP_PORT`, default `8088`. A probe of `localhost:8080` answers
  from ntfy, which looks like success and is not.
- **Eight bank docs are marked `inferred`.** They describe code that does not exist
  yet. Flip each to `confirmed` as its phase lands and the doc is checked against
  the real implementation.
- **No default-branch policy on GitHub**: the first pushed branch (`main`) is the
  default, so pull requests target `main` rather than `developing`.
