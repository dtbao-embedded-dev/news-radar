---
title: Progress
updated: 2026-09-05
---

# Progress

> Current delivery state - what works, what's left, known issues. Update at every checkpoint (feature shipped, milestone, direction change).

## What works

**P0 Foundation is released as v0.1.0; P1 Fetch and P2 Filter and rank are
complete** (2026-09-05).
See `architecture/delivery-phases.md` for the phase map and the finished-product
definition all of it serves.

### P2 - Filter and rank

- **`python -m news_radar --once` prints a shortlist, not a pile.** Measured in
  the container on 2026-09-05: **597 raw items -> 209 matched -> 205 stories
  after dedup -> 50 kept across 7 groups, exit 0**, in 37 s. That is P2's
  definition of done.
- **The global filter runs before any group sees the item.** `filter.blocked()`
  is called first by `select()`, so a story carrying `giveaway` cannot sneak in
  through a group that happens to match it.
- **Folding works on real Vietnamese titles.** A keyword typed `dien tu` finds
  `Điện tử`; `ESP32-S3` keeps its hyphen through folding, so the part number
  still matches. A `/regex/` runs against the **original** title - proven by a
  check that the lowercased form of a `CVE-2026-1234` title does not match
  `/CVE-\d{4}-\d+/`.
- **Every group is reported, empty ones included.** `Security - 0 item(s)` is a
  line in the run, not a missing section: a keyword that has gone quiet is
  exactly what a total would hide.
- **Layer 3 imports no config and reads no clock.** The weights, the
  `{source_id: rank_weight}` map and `now` are arguments; `__main__` builds
  them. That is why `test_filter.py` and `test_rank.py` run on a bare Python
  with neither PyYAML nor feedparser installed - seven of the nine test files
  now run on the host.
- **Two timestamp rules are pinned by tests, not by hope.** No `published_at`
  gives a freshness term of exactly `0`; a *future* timestamp scores no higher
  than one published now, because `0.5 ** negative` is greater than 1 and one
  bad `pubDate` would otherwise top every group.

### P1 - Fetch

- **`python -m news_radar --once` pulls real news.** Measured in the container
  on 2026-09-05: **597 raw items in 57 s, exit 0** - 208 from the eight fixed
  feeds and 389 from seven keyword groups crossed with two search templates.
  Both kinds of source contribute, which is exactly P1's definition of done.
- **One dead source costs one line, never the run.** `www.reddit.com` does not
  resolve from this homelab (`Name or service not known`, on the host and in the
  container alike - it is DNS, not the 403 the design predicted). The run
  reported it once, printed `r_embedded 0 item(s) [failed]`, and kept the other
  21 sources. `feeds.read_source()` is the single place that guard lives;
  `search.py` reuses it rather than repeating it.
- **Every source is counted by name, zeros included.** A feed that silently
  stops returning items looks identical to a quiet week inside a total, so the
  cycle prints a line per configured source rather than one grand number.
- **Three formats, dispatched on the declared type.** RSS 2.0 and Atom through
  `feedparser`, HN Algolia's JSON by hand - never on the response content type.
  Verified live against `lobste.rs` (25), `hackaday` (7) and Algolia (20),
  including a Show HN post with no outbound url falling back to its permalink.
- **Search queries are exact.** A multi-word primary term is quoted as a phrase
  before encoding (`%22embedded+linux%22`), and the template's own locale
  parameters survive character for character. `build_urls()` is pure, so the
  request count is known before the first byte goes out.
- **Five test files, none of which touch the network.** `test_item`,
  `test_keywords` and `test_http` need only the standard library (the last runs
  a local `http.server` to play a 403, a retryable 500, a gzipped body and a
  handler slow enough to time out); `test_feeds` and `test_search` read
  `tests/fixtures/`, one body per predicted edge case.
- **`keywords.py` landed early.** It is P2-1, written in P1 because the search
  generator needs each group's primary term and finding that correctly already
  means skipping every other prefix. It parses the shipped
  `config/frequency_words.txt` into its 7 groups with the right caps, labels,
  required terms and regex.

### P0 - Foundation

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
  `.github/workflows/test.yml` installs `requirements.txt`, then runs every
  `tests/test_*.py` on Python 3.12 - the loop picks up a new test file without
  the workflow being edited. Verified locally by running the same loop, by proving a
  failing check aborts it instead of passing silently, and by every green run
  since.
- **`setup.py` starts the stack itself, verified end to end.** A successful run
  ends with `docker compose up -d`, not a command printed for the operator to
  copy. Install is two steps, not three. Exercised on this machine on 2026-09-05
  with real credentials in `docker/.env`: exit 0, `[ok] stack is up -
  http://localhost:8088`, and Caddy answering `200` there. The failure paths were
  exercised too - a stopped daemon reports `docker compose exited 1` and returns
  non-zero, and a blank secret stops the run before docker is touched at all.
- **The docker stack is defined and Caddy actually runs.** Verified by starting
  it: Caddy serves `output/` with the `Cache-Control` headers from our Caddyfile.
- **The repository has a license.** Apache-2.0, in `LICENSE`, chosen because
  the clean-room decision left it free (`adr-0001`). The README states it and
  carries a badge.

- **The full stack starts, both services.** `Dockerfile` (base pinned by
  digest), `requirements.txt`, and the `src/news_radar/` skeleton exist, so
  `docker compose up -d` builds and runs the crawl service alongside Caddy.
  Verified on 2026-09-05: `setup.py` widened from `up -d caddy` to `up -d` on its
  own once the Dockerfile appeared, both containers report `Up`, and the crawl
  service logs its cycle then waits.
- **`python -m news_radar` runs.** Loads and validates the config, refuses to
  start when an enabled channel has no secret (verified in the container: three
  problems listed, exit 1), and honours `SIGTERM` mid-interval - `docker stop`
  returned in under a second because the loop waits on an Event rather than
  sleeping. `crawl()` was an honest placeholder at that point; P1 replaced it
  with the real fetch layer.
- **`python tests/test_config.py` passes.** Covers the default merge, the
  fatal-secret rule, and the validation gates, and asserts the committed
  `config.yaml.example` satisfies its own contract.

## What's left

Persistence onwards. `src/news_radar/` now holds the entrypoint, the config
loader, the item shape, the keyword parser, the whole fetch layer and the whole
selection layer; from `store.py` on, every stage module is still **specified but
not written**.

- **P3 Store and render** - SQLite store, the seen-set, and `output/index.html`.
- **P4 Notify** - Telegram and Discord senders, the new-only diff, and backoff.
- **P5 Deploy** - the Cloudflare Tunnel route for `news.dtbao.org` and the first
  unattended live run. The `Dockerfile` and the schedule loop are done.
- **P6 Ops** - retention, heartbeat, failure alerting.

## Known issues

- **The search templates answer relevance-first, not date-first.** Measured
  2026-09-05: Google News returned `ESP32` hits aged 1704-5783 hours, HN Algolia
  the same shape. At the default 12 h half-life the freshness term is `0` for
  nearly every search hit, so the shortlist ranks on source weight alone and the
  order inside a group is close to arbitrary. `published_at` itself is fine -
  the fixed feeds came back at 1.5 h and 18 h. The fix is narrowing both queries
  to a recent window in `config.yaml`, not code.

- **The pre-rewrite root commit is still reachable on GitHub.** History was
  rewritten on 2026-09-05 to drop a `Co-Authored-By` trailer, but a force push
  does not delete the old objects: `91ea2d9` still answers over the API with the
  trailer in it, and the repository is public. It clears when GitHub garbage
  collects, which cannot be triggered from here.
- **Four bank docs are still marked `inferred`**: `delivery-phases` and
  `deployment-homelab` (both describe work not done), `config-and-env` and
  `notify-channels` (never checked key by key against the code). Flip each once
  it is verified against the real implementation. P1 flipped `news-item`,
  `news-sources`, `news-search`, `module-layout` and `crawl-cli` to `confirmed`
  - note that the last two sections of `news-item` are still P3 and carry their
  own inline 🟡 marker.
- **`www.reddit.com` does not resolve from this homelab.** Both Reddit sources
  are therefore dead here, whatever User-Agent is sent. It is a network fact,
  not a code defect: failure isolation handles it, and the fixed feed stays
  enabled so the run reports it rather than hiding it. Fixing it means the
  homelab's DNS, not this repository.
- **Google News items are redirector links.** They arrive as
  `news.google.com/rss/articles/CBMi...`, so the same story from Google News and
  from Hacker News will not collapse on `canonical_url` in P2. Accepted, of the
  same class as the AMP limit already recorded.
- **`docker/docker-compose.yml` still carries a stale P0 note** saying the
  Dockerfile does not exist and only `caddy` is startable. That has been false
  since the Dockerfile landed.
- **No default-branch policy on GitHub**: the first pushed branch (`main`) is the
  default, so pull requests target `main` rather than `developing`.
