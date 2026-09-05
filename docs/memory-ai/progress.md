---
title: Progress
updated: 2026-09-05
---

# Progress

> Current delivery state - what works, what's left, known issues. Update at every checkpoint (feature shipped, milestone, direction change).

## What works

**P0 Foundation is complete and released as v0.1.0** (2026-09-05). See
`architecture/delivery-phases.md` for the phase map and the finished-product
definition all of it serves.

- **v0.1.0 is published.** `python scripts/release.py 0.1.0` ran the whole chain
  without stopping: promoted the changelog, wrote `VERSION`, committed on
  `release/v0.1`, merged into `developing` then `main`, tagged, returned, pushed
  all three branches and the tag. CI published the GitHub Release from the tag,
  with the `## v0.1.0` changelog section as its notes. Five workflow runs, all
  green. `main` carries real content for the first time.

- **The design bank is complete enough to build from.** Thirteen durable docs
  plus one ADR cover the target architecture, the sources and their exact URLs, the
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
- **`python scripts/release.py <version>` works, end to end.** It no longer
  reads the commit log: the changelog is hand-written into `## Unreleased` and
  the script promotes that section to the version, opening a fresh empty one.
  A missing or empty section fails the preflight - proven by emptying the section
  and watching a real run refuse with exit 1, nothing changed. `--dry-run` prints
  the body it would promote and the exact git chain. `python tests/test_release.py`
  passes with plain asserts and no test framework.
- **CI publishes a release from a tag.** `.github/workflows/release.yml` triggers
  on `v*`, cuts the version's section out of `CHANGELOG.md` using `release.py`'s
  own extractor, and falls back to GitHub-generated notes when there is no
  section. Both paths were exercised locally against the real workflow code.
- **CI runs the checks on every push and pull request.**
  `.github/workflows/test.yml` runs every `tests/test_*.py` on Python 3.12 with
  no install step. Verified locally by running the same loop, by proving a
  failing check aborts it instead of passing silently, and by every green run
  since.
- **`setup.py` starts the stack itself.** A successful run ends with
  `docker compose up -d`, not a command printed for the operator to copy. Install
  is two steps, not three. The success path has not been exercised on a machine
  with the Docker daemon running; the failure path was, and reports non-zero.
- **The docker stack is defined and Caddy actually runs.** Verified by starting
  it: Caddy serves `output/` with the `Cache-Control` headers from our Caddyfile.
- **The repository has a license.** Apache-2.0, in `LICENSE`, chosen because
  the clean-room decision left it free (`adr-0001`). The README states it and
  carries a badge.

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

- **The `news-radar` compose service cannot start.** It builds from a `Dockerfile`
  that lands in P5. Until then only `caddy` can start; the compose file says so
  and `setup.py` narrows itself to `caddy` on its own while the file is absent.
- **The pre-rewrite root commit is still reachable on GitHub.** History was
  rewritten on 2026-09-05 to drop a `Co-Authored-By` trailer, but a force push
  does not delete the old objects: `91ea2d9` still answers over the API with the
  trailer in it, and the repository is public. It clears when GitHub garbage
  collects, which cannot be triggered from here.
- **Host port 8080 is taken by ntfy on this homelab.** Caddy is published on
  `NEWS_RADAR_HTTP_PORT`, default `8088`. A probe of `localhost:8080` answers
  from ntfy, which looks like success and is not.
- **Eight bank docs are marked `inferred`.** They describe code that does not exist
  yet. Flip each to `confirmed` as its phase lands and the doc is checked against
  the real implementation.
- **No default-branch policy on GitHub**: the first pushed branch (`main`) is the
  default, so pull requests target `main` rather than `developing`.
