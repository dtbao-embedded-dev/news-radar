---
title: Module Layout and Stack
category: architecture
purpose: The directory tree news-radar is built as, its layering rules, and every dependency it is allowed to take.
status: active
updated: 2026-09-05
source: src/news_radar/, Dockerfile, requirements.txt
confidence: confirmed
keywords: tree, layout, layering, ops.py, layer 5, dependencies, pyyaml, feedparser, python 3.12, src/news_radar, scripts, docker
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
│   ├── item.py                 # DONE - NewsItem, canonical url, dedup key, fold
│   ├── keywords.py             # DONE - parse frequency_words.txt (landed in P1)
│   ├── fetch/                  # DONE - P1
│   │   ├── http.py             # UA, timeout, retry, per-host throttle
│   │   ├── feeds.py            # rss/atom/json -> items, fixed feeds, isolation
│   │   └── search.py           # keyword -> search URL -> items
│   ├── filter.py               # DONE - global filter + match against groups
│   ├── rank.py                 # DONE - dedup + weighted ranking + @n cap
│   ├── store.py                # DONE - SQLite persistence, seen-set, retention, backup
│   ├── render.py               # DONE - output/index.html + days/<date>.html
│   ├── ops.py                  # DONE - P6: heartbeat, Health, ALERT_AFTER
│   └── notify/                 # DONE - P4
│       ├── __init__.py         # SendResult, pick, chunk, clip
│       ├── telegram.py         # bot API, HTML, 4000; alert() has no parse_mode
│       └── discord.py          # webhook, Markdown, 2000; alert() is escaped
├── tests/
│   ├── test_config.py          # plain asserts, needs PyYAML
│   ├── test_item.py            # plain asserts, stdlib only
│   ├── test_keywords.py        # plain asserts, stdlib only
│   ├── test_http.py            # plain asserts, stdlib only, local http.server
│   ├── test_feeds.py           # plain asserts, needs feedparser + PyYAML
│   ├── test_search.py          # plain asserts, needs feedparser + PyYAML
│   ├── test_filter.py          # plain asserts, stdlib only
│   ├── test_rank.py            # plain asserts, stdlib only
│   ├── test_store.py           # plain asserts, stdlib only (sqlite3)
│   ├── test_render.py          # plain asserts, stdlib only
│   ├── test_notify.py          # plain asserts, stdlib only, local http.server
│   ├── test_release.py         # plain asserts, stdlib only
│   └── fixtures/               # one feed body per edge case, no network
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
| 2 — sources | `fetch/feeds.py`, `fetch/search.py` | layer 1, `config`, `keywords`, `item` |
| 3 — selection | `filter.py`, `rank.py` | `keywords`, `item`, plain data types |
| 4 — persistence | `store.py` | stdlib, `item`, layer 3 output types |
| 5 — output | `render.py`, `notify/*`, `ops.py` | layers 3 and 4; `notify/*` and `ops.py` also layer 1 |

`ops.py` sits in layer 5 for the same reason `notify/*` does and imports layer 1
for the same reason too - the heartbeat's site check and its ping are GETs, and
they want the User-Agent, the timeout, the retry and the per-host gap the
`Fetcher` already has. It imports no config and reads no clock: both urls and the
verdict on the cycle arrive as arguments that `__main__.py` builds, which is why
`tests/test_ops.py` runs against a local `http.server` with nothing installed.
See [[config-and-env]] for the keys and [[delivery-phases]] for why the ping is
withheld rather than sent on a bad cycle.

`notify/*` reaching back to layer 1 is the one deliberate widening: a POST needs
the same User-Agent, timeout, retry and per-host gap a GET does, and honouring a
429's `Retry-After` is a transport concern rather than a per-channel one. The
alternative was a second HTTP client inside `notify/`. See [[notify-channels]].

`__main__.py` is the only module that knows about all five; it wires them and owns
the schedule loop. `config.py`, `item.py` and `keywords.py` are leaves — they
import nothing from the package, which is why each has a test that needs neither
PyYAML nor feedparser to run.

Layer 3 taking no `config` import is not a style preference either: the weights
and the `source_id -> rank_weight` map are plain dicts `__main__.py` builds and
hands down, which is why `test_filter.py` and `test_rank.py` run on a bare
Python with no dependency installed. See [[selection-layer]].

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
| Templating | stdlib f-strings | One page. A template engine is a dependency for nothing |
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
