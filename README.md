# News Radar

[![Test](https://github.com/dtbao-embedded-dev/news-radar/actions/workflows/test.yml/badge.svg)](https://github.com/dtbao-embedded-dev/news-radar/actions/workflows/test.yml)
[![Version](https://img.shields.io/github/v/release/dtbao-embedded-dev/news-radar?sort=semver&display_name=tag&label=version)](https://github.com/dtbao-embedded-dev/news-radar/releases)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)](#requirements)

> A self-hosted news radar. It hunts stories on a schedule, filters them against
> your own keyword file, publishes them to <https://news.dtbao.org>, and pushes
> only the new matches to Telegram and Discord.

Nothing about it is hosted for you: the crawl and the site both run on your own
machine, and the only things that leave it are the feed requests and the
notifications you asked for.

## How it hunts

Two ways of hunting feed one filter.

| | Where the stories come from | Who does the first cut |
|---|---|---|
| **Fixed feeds** | Hacker News, Lobsters, Hackaday, LWN, r/embedded, VnExpress So hoa, GenK, Tinh te | fetched whole, filtered locally |
| **Search feeds** | Google News RSS, HN Algolia, Reddit search | built at runtime from each keyword group, so the keyword travels into the URL and the source filters first |

Adding a keyword adds a hunting path. No code changes.

Everything fetched then passes one pipeline: filter against the keyword groups,
collapse duplicates that arrived from several sources onto one dedup key, rank
by source rank + how many sources carried the story + freshness, and report only
what has not been reported before.

## Status

**P0 Foundation.** The design is complete and the tooling works; the application
layer is specified but not written yet.

| | |
|---|---|
| **Runs today** | `scripts/setup.py`, `scripts/release.py`, both CI workflows, the Caddy half of the docker stack |
| **Not written yet** | `src/news_radar/` — fetch, filter, rank, store, render, notify |
| **Next** | P1 Fetch, once the `Dockerfile` and the package skeleton exist |

`docs/memory-ai/progress.md` says exactly what works and what is left;
`docs/memory-ai/architecture/delivery-phases.md` has the phase map (P0–P6).

## Requirements

- **Python 3.11+** — `setup.py` and `release.py` are standard library only, so
  they run on a bare checkout before anything is installed.
- **Docker Engine + Compose v2** — for the stack.
- Two runtime dependencies, total: `pyyaml` and `feedparser`. HTTP, storage and
  templating come from the standard library.

## Quick start

```bash
git clone git@github.com:dtbao-embedded-dev/news-radar.git
cd news-radar
python scripts/setup.py
docker compose -f docker/docker-compose.yml up -d caddy
```

Same steps on Windows and Linux. `setup.py` checks Python and Docker, creates
`config/config.yaml` and `docker/.env` from their templates without ever
overwriting an existing file, and asks for the Telegram and Discord secrets. Run
it with `--dry-run` first to see what it would do.

> **At P0, start `caddy` only.** The `news-radar` crawl service builds from a
> `Dockerfile` that lands in P5, so a plain `up -d` fails on the build. Caddy
> serves `output/` on `NEWS_RADAR_HTTP_PORT` (default `8088`).

Full procedure: `docs/memory-ai/rule/setup-homelab.md`.

## Configuration

| File | Holds |
|---|---|
| `config/config.yaml` | feeds, search templates, schedule, ranking weights |
| `config/frequency_words.txt` | the keyword groups |
| `docker/.env` | secrets only — never committed |

Keyword file syntax: a blank line separates groups; `+` requires a word, `!`
excludes one, `@n` caps a group, `/re/` matches by regex.

`config.yaml` is committed as a template and a leaked copy must be harmless —
every secret lives in `docker/.env` instead. Every key is documented in
`docs/memory-ai/interface/config-and-env.md`.

## Development

```bash
python tests/test_release.py
```

Plain asserts, no test framework, no fixtures. CI runs every `tests/test_*.py`
on each push and pull request.

Commit subjects follow Conventional Commits — they *are* the changelog, so a
subject that does not parse shows up under "Other".

## Releasing

```bash
python scripts/release.py 0.2.0 --dry-run   # see the whole plan, change nothing
python scripts/release.py 0.2.0             # cut it
```

Writes the changelog from the commit subjects since the last tag, commits
`chore(release): v0.2.0` on `release/*`, merges into `developing` then `main`,
tags, returns to the release branch, and pushes. CI turns the tag into a GitHub
Release using that changelog section.

Branch model: `main` (released) ← `developing` (integration) ← `release/<minor>`
(day-to-day work). Full rules: `docs/memory-ai/rule/release-flow.md`.

## Documentation

Everything lives in `docs/memory-ai/`, as prose and tables — never pasted source.

| Read | For |
|---|---|
| `memory.md` | the whole design in one pass |
| `overview.md` | finding a single topic |
| `progress.md`, `active-context.md` | where the work is right now |

Each statement carries a confidence marker: 🟢 confirmed (cited from code),
🟡 inferred (verify before relying on it), 🔴 gap (needs a human).

## Prior art

[TrendRadar](https://github.com/sansan0/TrendRadar) solves the same shape of
problem and is worth reading when a specific problem here gets hard. News Radar
is written from scratch and shares no code with it — it is GPL-3.0 and this is a
clean-room reimplementation. See
`docs/memory-ai/adr/adr-0001-clean-room-from-trendradar.md` for the decision and
`docs/memory-ai/rule/reference-trendradar.md` for what may never be copied back.

## License

**Not chosen yet.** The clean-room decision exists precisely so this repository
is free to pick one; nobody has. Until a `LICENSE` file lands, no license is
granted.
