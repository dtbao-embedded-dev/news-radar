---
title: Module Layout and Stack
category: architecture
purpose: The directory tree news-radar is built as, its layering rules, and every dependency it is allowed to take.
status: active
updated: 2026-09-05
source: conversation
confidence: inferred
keywords: tree, layout, layering, dependencies, pyyaml, feedparser, python 3.12, src/news_radar, scripts, docker
order: 2
---

# Module Layout and Stack

> One Python package under `src/`, two stdlib-only scripts under `scripts/`, and
> a docker stack under `docker/`. Data flows one way: fetch -> filter -> rank ->
> store -> render/notify. No back edges.

## Tree

```
news-radar/
├── config/
│   ├── config.yaml.example     # template, committed
│   ├── config.yaml             # real, gitignored, created by setup.py
│   └── frequency_words.txt     # keyword groups, committed
├── docker/
│   ├── docker-compose.yml      # crawl service + caddy
│   ├── Caddyfile               # serves output/ on :8080
│   ├── .env.example            # template, committed
│   └── .env                    # secrets, gitignored, created by setup.py
├── scripts/
│   ├── setup.py                # homelab bootstrap, stdlib only
│   └── release.py              # release automation, stdlib only
├── Dockerfile                  # crawl service image, base pinned by digest
├── requirements.txt            # the two runtime dependencies, pinned
├── src/news_radar/
│   ├── __init__.py             # DONE - __version__, read from VERSION
│   ├── __main__.py             # DONE - entrypoint + schedule loop
│   ├── config.py               # DONE - load + validate config.yaml and env
│   ├── keywords.py             # P2 - parse frequency_words.txt
│   ├── fetch/                  # P1
│   │   ├── http.py             # UA, timeout, retry, per-host throttle
│   │   ├── feeds.py            # fixed RSS/Atom sources
│   │   └── search.py           # keyword -> search URL -> items
│   ├── filter.py               # P2 - match items against keyword groups
│   ├── rank.py                 # P2 - dedup + weighted ranking
│   ├── store.py                # P3 - SQLite persistence + seen-set
│   ├── render.py               # P3 - output/index.html
│   └── notify/                 # P4
│       ├── telegram.py
│       └── discord.py
├── tests/
│   ├── test_config.py          # plain asserts, needs PyYAML
│   └── test_release.py         # plain asserts, stdlib only
├── output/                     # gitignored: index.html, news.db, per-day files
├── docs/memory-ai/             # this bank
├── .github/workflows/
│   ├── test.yml                # runs tests/test_*.py on push and PR
│   └── release.yml             # tag -> GitHub Release
├── LICENSE                     # Apache-2.0
├── CHANGELOG.md
├── VERSION
└── README.md
```

## Layering

Five layers, each importing only downward. A violation is a bug, not a style
preference: it is what makes the pipeline impossible to test one stage at a time.

| Layer | Modules | May import |
|-------|---------|-----------|
| 1 — transport | `fetch/http.py` | stdlib only |
| 2 — sources | `fetch/feeds.py`, `fetch/search.py` | layer 1, `config`, `keywords` |
| 3 — selection | `filter.py`, `rank.py` | `keywords`, plain data types |
| 4 — persistence | `store.py` | layer 3 output types |
| 5 — output | `render.py`, `notify/*` | layers 3 and 4 |

`__main__.py` is the only module that knows about all five; it wires them and owns
the schedule loop. `config.py` and `keywords.py` are leaves — they import nothing
from the package.

`scripts/` is outside the package entirely and imports nothing from it: both
scripts must run on a machine where the package's dependencies are not installed
yet. That is the whole point of `setup.py`.

## Stack and dependencies

| Concern | Choice | Why not something else |
|---------|--------|------------------------|
| Language | Python 3.12 | Already on the target machines; `release.py` was specified as Python |
| Config format | YAML via **PyYAML** | The config is hand-edited; JSON has no comments |
| Feed parsing | **feedparser** | Twenty years of malformed RSS/Atom in the wild. Hand-rolling `xml.etree` here is the classic mistake |
| HTTP | stdlib `urllib.request` | One GET with a User-Agent and a timeout. `requests` earns nothing here |
| Storage | stdlib `sqlite3` | Single writer, single file, no server to run |
| Templating | stdlib `string.Template` / f-strings | One page. A template engine is a dependency for nothing |
| Web server | Caddy (container) | Static files plus automatic HTTPS if ever served directly |
| Scheduling | in-process loop in the crawl container | Compose has no cron; a host cron differs between Windows and Linux |

**Runtime dependencies: `pyyaml`, `feedparser`. That is the entire list.** Adding
a third needs a line in the changelog saying what it replaced.

`scripts/setup.py` and `scripts/release.py` use **stdlib only** — no PyYAML, no
feedparser — so they work on a bare Python install.

## Configuration precedence

Lowest to highest:

1. Defaults compiled into `config.py`
2. `config/config.yaml`
3. Environment variables (`docker/.env` in the container, real env outside)

Secrets — bot tokens, webhook URLs — live **only** in the environment layer.
`config.yaml` never holds one; it is committed as `.example` and a leaked copy
must be harmless.
