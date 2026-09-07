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

- **Docker Engine + Compose v2** — for the stack. This is the only requirement
  for running it.
- **Python 3.11+** — only to develop: `setup.py` and `release.py` are standard
  library only, so they run on a bare checkout before anything is installed.
- Two runtime dependencies, total: `pyyaml` and `feedparser`. HTTP, storage and
  templating come from the standard library.

## Running it

The package is a **container image**, not a source checkout. A deployment holds
its own data and a compose file, and nothing else — no git, so no command on
that machine can clean `config/`, `output/` or `backups/`.

```bash
mkdir -p ~/news-radar/config ~/news-radar/output ~/news-radar/backups
cd ~/news-radar
BASE=https://raw.githubusercontent.com/dtbao-embedded-dev/news-radar/v<version>
curl -fsSLO "$BASE/docker/docker-compose.yml"
curl -fsSLO "$BASE/docker/Caddyfile"
curl -fsSL  "$BASE/docker/.env.example"                -o .env
curl -fsSL  "$BASE/config/config.yaml.example"         -o config/config.yaml
curl -fsSL  "$BASE/config/frequency_words.txt.example" -o config/frequency_words.txt
# edit .env: the Telegram/Discord secrets, and NEWS_RADAR_HOME=.
docker compose pull
docker compose up -d
```

Updating is `docker compose pull && docker compose up -d`, or nothing at all —
`--profile autoupdate` runs a watchtower container that does it for you once a
day. `docker compose run --rm news-radar --check` names any config key a release
added and your `config.yaml` has not got. See
[docs/memory-ai/rule/updating-homelab.md](docs/memory-ai/rule/updating-homelab.md)
for the migration from an older checkout and how to pin a version.

The report is served on the LAN and **published nowhere** — there is no tunnel
and no reverse proxy in this stack. Putting it on the internet is a decision for
whatever you choose to front it with, made outside this project.

## Developing it

```bash
git clone git@github.com:dtbao-embedded-dev/news-radar.git
cd news-radar
python scripts/setup.py
```

Same two steps on Windows and Linux. `setup.py` checks Python and Docker,
creates `config/config.yaml`, `config/frequency_words.txt` and `docker/.env`
from their templates without ever overwriting an existing file, asks for the
Telegram and Discord secrets, then builds the image locally and brings the stack
up.

The stories arrive on Telegram and Discord. The **HTML report ships off**
(`report.html: false`): set it to `true` in `config/config.yaml` to publish the
page as well, served on `http://localhost:8088` and overridable with
`NEWS_RADAR_HTTP_PORT`.

| Flag | For |
|---|---|
| `--dry-run` | See every step, including the compose command. Writes nothing, starts nothing |
| `--check` | Verify an existing checkout, secrets included. Creates nothing, starts nothing, non-zero on a gap |
| `--non-interactive` | Unattended: report a blank secret instead of prompting |
| `--force` | Regenerate a config file from its template on purpose |

A compose failure is reported and exits non-zero — the script never claims a
stack it could not start. While the checkout has no `Dockerfile` the crawl
service cannot build, so only the web half is started and the script says so.

## Configuration

| File | Holds |
|---|---|
| `config/config.yaml` | feeds, search templates, schedule, ranking weights |
| `config/frequency_words.txt` | the keyword groups — created from `frequency_words.txt.example`, gitignored so an upgrade never reverts your tuning |
| `.env` | secrets, the published port, and where the data lives — never committed. `docker/.env` in a checkout |

`NEWS_RADAR_HOME` in `.env` is the one that decides where `config/`, `output/`
and `backups/` are read from, relative to the compose file: unset it is `..`,
the repository root, which is what a checkout wants; a deployment sets `.`.

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

Commit subjects follow Conventional Commits. The changelog is separate and
hand-written: when a change alters what the software does or how it is built,
add a line to the `Unreleased` section of `CHANGELOG.md` in the same commit.
Documentation, chores, CI and tests do not get an entry.

## Releasing

```bash
python scripts/release.py 0.2.0 --dry-run   # see the whole plan, change nothing
python scripts/release.py 0.2.0             # cut it
```

Renames the `Unreleased` section of `CHANGELOG.md` to the version, commits
`chore(release): v0.2.0` on `release/*`, merges into `developing` then `main`,
tags, returns to the release branch, and pushes. CI turns the tag into a GitHub
Release using that changelog section. A release with nothing recorded under
`Unreleased` is refused.

Branch model: `main` (released) ← `developing` (integration) ← `release/<minor>`
(day-to-day work). `--dry-run` prints the exact git chain before anything runs;
use it first.

## Prior art

[TrendRadar](https://github.com/sansan0/TrendRadar) solves the same shape of
problem and is worth reading. News Radar is a clean-room reimplementation: it is
written from scratch and shares no code with it.

## License

[Apache License 2.0](LICENSE). Copyright 2026 dtbao.
