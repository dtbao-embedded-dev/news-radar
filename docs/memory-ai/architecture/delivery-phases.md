---
title: Delivery Phases
category: architecture
purpose: The finished product news-radar aims at, and the phase-by-phase task breakdown that gets there.
status: active
updated: 2026-09-05
source: conversation
confidence: inferred
keywords: roadmap, phases, P0, P1, P2, P3, P4, P5, P6, scope, milestones, definition of done
order: 1
---

# Delivery Phases

> news-radar is a self-hosted news radar: it hunts stories on a schedule, filters
> them against your own keyword file, publishes them to https://news.dtbao.org,
> and pushes only the new matches to Telegram and Discord.

## The finished product

Six statements define "done". Every phase below exists to make one of them true.

1. **It hunts on its own.** A crawl container runs on a schedule (default every
   30 minutes). It pulls the fixed feeds *and* builds search feeds from **each
   keyword group** in `frequency_words.txt`. Adding a keyword adds a hunting
   path — no code change.
2. **It filters for you.** Everything fetched passes one filter: required words
   `+`, excluded words `!`, per-group cap `@`, regex. Duplicates collapse on a
   dedup key; survivors are ranked by source rank + how many sources carried the
   story + freshness.
3. **Opening https://news.dtbao.org is enough to read it.** Caddy serves
   `output/`, exposed through a Cloudflare Tunnel. The page groups stories by
   keyword group, has a dark mode, a search box, and per-day history.
4. **New stories come to you.** Each crawl pushes only the **new** matches to
   Telegram and Discord. Nothing is re-sent.
5. **Installing on a new machine is three steps.** `git clone` →
   `python scripts/setup.py` (fill in tokens) → `docker compose up -d`.
   Identical on Windows and Linux.
6. **Releasing is one command.** `python scripts/release.py 0.2.0` writes the
   changelog, commits `chore(release): v0.2.0` on `release/*`, merges into
   `developing` then `main`, tags, returns to `release/*` and pushes. CI turns
   the tag into a GitHub Release.

All of it is written from scratch. TrendRadar is read for *how they solved a
problem*, never copied — see [[reference-trendradar]] and
`adr/adr-0001-clean-room-from-trendradar.md`.

## Phases

Each phase is shippable on its own: it ends in something a human can run and see.

| Phase | Goal | Phase is done when |
|-------|------|--------------------|
| P0 | Foundation: the design bank, config templates, docker skeleton, setup + release tooling | `setup.py --dry-run` and `release.py --dry-run` both run; the bank passes `validate --strict` |
| P1 | Fetch: get raw items out of every source | One command prints N raw items pulled from all fixed feeds *and* from keyword-built search feeds |
| P2 | Filter and rank: turn raw items into the shortlist | The same command prints grouped, deduped, ranked matches instead of raw items |
| P3 | Store and render: persist and publish a page | `output/index.html` opens in a browser and shows today's matches; history survives a restart |
| P4 | Notify: push the new ones | A crawl with new matches lands exactly one message in Telegram and one in Discord; a crawl with none sends nothing |
| P5 | Deploy: run it for real on the homelab | https://news.dtbao.org serves the current report, refreshed unattended |
| P6 | Ops: keep it alive without babysitting | Seven days unattended with no manual intervention and no disk growth |

## Task breakdown

### P0 — Foundation *(this repo's current phase)*

| # | Task |
|---|------|
| P0-1 | Design bank: `architecture/` (this doc, module layout, deployment) + clean-room ADR |
| P0-2 | Design bank: `data/` — source table with the exact URL patterns, item shape, dedup key, `output/` layout |
| P0-3 | Design bank: `interface/` — config keys, keyword-file syntax, env vars, script CLIs, notification channel contracts; `behavior/news-search.md` |
| P0-4 | Config templates and docker skeleton: `config.yaml.example`, `frequency_words.txt`, `docker-compose.yml`, `Caddyfile`, `.env.example` |
| P0-5 | `scripts/setup.py` — one script, same behaviour on Windows and Linux |
| P0-6 | `scripts/release.py` + `tests/test_release.py` |
| P0-7 | CI: check workflow on push/PR + tag-triggered release workflow, `CHANGELOG.md`, `VERSION` |
| P0-8 | Design bank: `rule/` — release procedure, setup procedure, how to consult TrendRadar |

### P1 — Fetch

| # | Task |
|---|------|
| P1-1 | HTTP client: explicit User-Agent, timeout, retry with backoff, per-host minimum interval |
| P1-2 | Feed parser: RSS 2.0 + Atom + the broken variants in the wild (use `feedparser`, do not hand-roll) |
| P1-3 | Fixed-feed reader: read `platforms`/`feeds` from config, fetch each, tag every item with its source id |
| P1-4 | Search-feed generator: expand each keyword group into the three search URL templates, fetch, tag |
| P1-5 | Failure isolation: one dead source must never abort the crawl — log it, keep the rest |
| P1-6 | JSON-API source support (HN Algolia returns JSON, not a feed) |

### P2 — Filter and rank

| # | Task |
|---|------|
| P2-1 | Parse `frequency_words.txt`: groups, `+` required, `!` excluded, `@` cap, `/regex/`, display label |
| P2-2 | Match engine: decide which groups an item belongs to, case- and diacritic-insensitive |
| P2-3 | Global filter section applied before grouping |
| P2-4 | Dedup: collapse the same story arriving from several sources onto one dedup key |
| P2-5 | Rank: weighted sum of source rank, cross-source frequency, and freshness; weights live in config |
| P2-6 | Per-group cap `@n` applied after ranking |

### P3 — Store and render

| # | Task |
|---|------|
| P3-1 | SQLite store: items, sources, per-run log; schema migration on open |
| P3-2 | Seen-set: what has already been reported, so P4 can diff |
| P3-3 | HTML renderer: one self-contained `output/index.html`, grouped by keyword group |
| P3-4 | Page features: dark mode, client-side search, per-day history navigation |
| P3-5 | Retention: prune rows and files older than the configured window |

### P4 — Notify

| # | Task |
|---|------|
| P4-1 | Telegram sender: bot API, message length limit, HTML/Markdown escaping |
| P4-2 | Discord sender: webhook, embed limits, 2000-character body limit |
| P4-3 | New-only diff against the seen-set; nothing new means nothing sent |
| P4-4 | Batching and backoff: respect 429 and `Retry-After` on both channels |
| P4-5 | Report modes: current run / daily digest / incremental |

### P5 — Deploy

| # | Task |
|---|------|
| P5-1 | Dockerfile for the crawl service; pin the base image |
| P5-2 | Compose: crawl service with an internal schedule loop + Caddy serving `output/` |
| P5-3 | Cloudflare Tunnel route for `news.dtbao.org` |
| P5-4 | First live run on the homelab, verified from outside the LAN |

### P6 — Ops

| # | Task |
|---|------|
| P6-1 | Heartbeat: a run that fails silently must be visible |
| P6-2 | Failure alerting into the same Telegram/Discord channels |
| P6-3 | Backup and restore of the SQLite store |
| P6-4 | Optional AI summary of the day's matches |

## What is deliberately not in scope

- No multi-user accounts, no login, no write API — the page is read-only output.
- No comment scraping, no full-article extraction: titles, links, timestamps only.
- No mobile app; the page is responsive and that is the whole client story.
