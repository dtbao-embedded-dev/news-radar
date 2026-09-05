# News Radar

[![Test](https://github.com/dtbao-embedded-dev/news-radar/actions/workflows/test.yml/badge.svg)](https://github.com/dtbao-embedded-dev/news-radar/actions/workflows/test.yml)
[![Version](https://img.shields.io/github/v/release/dtbao-embedded-dev/news-radar?sort=semver&display_name=tag&label=version)](https://github.com/dtbao-embedded-dev/news-radar/releases)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)](#requirements)

> A self-hosted news radar. It hunts stories on a schedule, filters them against
> your own keyword file, renders them to a static page you serve yourself, and
> pushes only the new matches to Telegram and Discord.

Nothing about it is hosted for you. The crawl and the site both run on your own
machine, the page is served from a directory on disk, and the only things that
leave the box are the feed requests and the notifications you asked for. Where
that page is reachable from — a LAN address, a tunnel, a reverse proxy, nothing
at all — is your choice, not a setting baked into the project.

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
docker compose -f docker/docker-compose.yml up -d
```

Same steps on Windows and Linux. `setup.py` checks Python and Docker, creates
`config/config.yaml` and `docker/.env` from their templates without ever
overwriting an existing file, and asks for the Telegram and Discord secrets. Run
it with `--dry-run` first to see what it would do, and `--check` to verify an
existing checkout without writing anything.

The crawl service builds from a `Dockerfile`. While that file is absent from the
checkout, a full `up -d` dies on the build and only the web half can start:

```bash
docker compose -f docker/docker-compose.yml up -d caddy
```

`setup.py` ends by printing whichever of the two commands applies — follow that
line. Caddy serves the rendered page on `NEWS_RADAR_HTTP_PORT`, default `8088`.

## Configuration

| File | Holds |
|---|---|
| `config/config.yaml` | feeds, search templates, schedule, ranking weights |
| `config/frequency_words.txt` | the keyword groups |
| `docker/.env` | secrets and the published port — never committed |

Keyword file syntax: a blank line separates groups; `+` requires a word, `!`
excludes one, `@n` caps a group, `/re/` matches by regex.

`config.yaml` is committed as a template and a leaked copy must be harmless —
every secret lives in `docker/.env` instead. Both real files are gitignored and
`setup.py` creates them from `.example` templates.

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
(day-to-day work). `--dry-run` prints the exact git chain before anything runs;
use it first.

## Prior art

[TrendRadar](https://github.com/sansan0/TrendRadar) solves the same shape of
problem and is worth reading. News Radar is a clean-room reimplementation: it is
written from scratch and shares no code with it.

## License

[Apache License 2.0](LICENSE). Copyright 2026 dtbao.
