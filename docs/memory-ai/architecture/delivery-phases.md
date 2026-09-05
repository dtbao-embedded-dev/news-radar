---
title: Delivery Phases
category: architecture
purpose: The finished product news-radar aims at, and the phase-by-phase task breakdown that gets there.
status: active
updated: 2026-09-05
source: conversation, CHANGELOG.md
confidence: confirmed
keywords: roadmap, phases, P0, P1, P2, P3, P4, P5, P6, P6-4, ai summary, scope, milestones, definition of done
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
5. **Installing on a new machine is two steps.** `git clone` →
   `python scripts/setup.py` (fill in tokens); the script brings the stack up
   itself. Identical on Windows and Linux.
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
| P6 | Ops: keep it alive without babysitting | Seven days unattended with no manual intervention and no disk growth — **the code is built, the seven days are running** |

## Task breakdown

### P0 — Foundation *(done, v0.1.0)*

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

### P1 — Fetch *(done)*

| # | Task |
|---|------|
| P1-1 | ~~HTTP client: explicit User-Agent, timeout, retry with backoff, per-host minimum interval~~ — `fetch/http.py` |
| P1-2 | ~~Feed parser: RSS 2.0 + Atom + the broken variants in the wild~~ — `fetch/feeds.py`, via `feedparser` |
| P1-3 | ~~Fixed-feed reader: read `feeds` from config, fetch each, tag every item with its source id~~ — `read_fixed_feeds()` |
| P1-4 | ~~Search-feed generator: expand each keyword group into the search URL templates, fetch, tag~~ — `fetch/search.py` |
| P1-5 | ~~Failure isolation: one dead source must never abort the crawl~~ — `read_source()`, the single guard |
| P1-6 | ~~JSON-API source support (HN Algolia returns JSON, not a feed)~~ — folded into P1-2 as a third format |

**P2-1 landed here too.** `keywords.py` parses the whole file already, because
finding a group's primary term means skipping every other prefix anyway.

### P2 — Filter and rank *(done)*

| # | Task |
|---|------|
| P2-1 | ~~Parse `frequency_words.txt`: groups, `+` required, `!` excluded, `@` cap, `/regex/`, display label~~ — **done in P1**, `keywords.py` |
| P2-2 | ~~Match engine: decide which groups an item belongs to, case- and diacritic-insensitive~~ — `filter.group_matches()` |
| P2-3 | ~~Global filter section applied before grouping~~ — `filter.blocked()`, called first by `select()` |
| P2-4 | ~~Dedup: collapse the same story arriving from several sources onto one dedup key~~ — `rank.collapse()` |
| P2-5 | ~~Rank: weighted sum of source rank, cross-source frequency, and freshness; weights live in config~~ — `rank.score()` |
| P2-6 | ~~Per-group cap `@n` applied after ranking~~ — `rank.rank_groups()` |

**The search templates are the weak link P2 exposed.** Google News and HN
Algolia answer a query relevance-first, not date-first, so their hits are often
months old and the freshness term is `0` for nearly all of them - the shortlist
currently ranks on source weight alone. Narrowing both queries to a recent
window is a `config.yaml` change, not a code one.

### P3 — Store and render *(done)*

| # | Task |
|---|------|
| P3-1 | ~~SQLite store: items, sources, per-run log; schema migration on open~~ — `store.py`, five tables, `user_version` |
| P3-2 | ~~Seen-set: what has already been reported, so P4 can diff~~ — `unreported()` / `mark_reported()`, keyed per channel |
| P3-3 | ~~HTML renderer: one self-contained `output/index.html`, grouped by keyword group~~ — `render.write()` |
| P3-4 | ~~Page features: dark mode, client-side search, per-day history navigation~~ — inline CSS and ~40 lines of JS, no library |
| P3-5 | ~~Retention: prune rows and files older than the configured window~~ — `store.prune()` |

**The page is rendered from the store, not from the run in memory.** `day_matches()` returns the whole local day, which is what makes a restart at noon still publish what the morning found - the phase's definition of done. Signatures are in [[storage-layer]].

**P2's weak link was closed here too.** Narrowing Google News to `when:7d` and querying HN Algolia through `search_by_date` finally makes the freshness term fire; what it cost in volume is in `progress.md`.

### P4 — Notify *(done)*

| # | Task |
|---|------|
| P4-1 | ~~Telegram sender: bot API, message length limit, HTML/Markdown escaping~~ — `notify/telegram.py`, HTML at 4000 |
| P4-2 | ~~Discord sender: webhook, embed limits, 2000-character body limit~~ — `notify/discord.py`, plain `content` at 1900, no embeds |
| P4-3 | ~~New-only diff against the seen-set; nothing new means nothing sent~~ — `notify.pick()` over `store.unreported()` |
| P4-4 | ~~Batching and backoff: respect 429 and `Retry-After` on both channels~~ — `Fetcher.post_json()`, capped at 60 s |
| P4-5 | ~~Report modes: current run / daily digest / incremental~~ — `_rows_to_send()` picks the window, the diff picks the rest |

**A story is marked sent only after the message carrying it was accepted.** A
crash between the two re-sends; a duplicate is the acceptable failure where a
silently dropped story is not. Signatures are in [[notify-channels]].

### P5 — Deploy *(done)*

| # | Task |
|---|------|
| P5-1 | ~~Dockerfile for the crawl service; pin the base image~~ - **done early**, it blocked every P1 verification |
| P5-2 | ~~Compose: crawl service with an internal schedule loop + Caddy serving `output/`~~ - `docker/docker-compose.yml` |
| P5-3 | ~~Cloudflare Tunnel route for `news.dtbao.org`~~ - a `cloudflared` service in the same stack, behind the `tunnel` profile |
| P5-4 | ~~First live run on the homelab, verified from outside the LAN~~ - `https://news.dtbao.org/` answers `200` |

**The connector runs in the stack, not on the host.** That is what lets the
origin be `caddy:8080` at all, and it keeps the news route from sharing a
restart with whatever else a host connector is carrying. The tunnel id lives in
a committed `docker/cloudflared.yml`; only the credentials file is a secret.
Details in [[deployment-homelab]], the procedure in [[setup-homelab]].

### P6 — Ops *(built, P6-4 included; the seven unattended days are still running)*

| # | Task |
|---|------|
| P6-1 | ~~Heartbeat: a run that fails silently must be visible~~ - `ops.heartbeat()`, a site check then a dead-man's-switch ping |
| P6-2 | ~~Failure alerting into the same Telegram/Discord channels~~ - `ops.Health` + `alert()` on both channels |
| P6-3 | ~~Backup and restore of the SQLite store~~ - `store.backup()`, restore documented in [[storage-layer]] |
| P6-4 | ~~Optional AI summary of the day's matches~~ - `summarize.py`, off by default; **dropped once, then built when a third of the reason expired** |

**A ping is a claim that the cycle worked**, and everything in P6-1 exists to
keep that claim from being made falsely: the published page is fetched *before*
the ping, and any problem anywhere in the cycle withholds it. That is what makes
silence the signal - a killed container, a host that lost power and a daemon that
never came back are indistinguishable from inside, so something outside has to be
the one expecting a request. The reverse asymmetry is deliberate too: a monitor
that refuses the ping is a warning, never an alert.

**Two messages per outage, whatever its length.** `ALERT_AFTER = 2` consecutive
failed cycles send one message naming the reasons; the first clean cycle after
sends one saying it recovered. A broken thing repeats every thirty minutes, and
an alert that repeats with it is one you learn to swipe away - taking the next
real one with it.

**P6-4 was dropped on its own terms, and then built when one of those terms
expired.** The drop rested on three costs: an API key, a per-run bill, and a
third runtime dependency against a two-dependency rule the project has held
since P0. P4 retired the third without anyone noticing at the time -
`Fetcher.post_json()` exists, so an OpenAI-compatible `/v1/chat/completions` is
a POST with a bearer header and no new import. What remained was a key and a
bill, and both are opt-in: `ai.enabled` ships `false`, so a config that says
nothing about `ai` never reaches the network. Naming the *wire format* rather
than a vendor is what makes the bill optional too - OpenRouter, DeepSeek, Groq
and a local Ollama all answer the same endpoint, and the last costs nothing.

**The summary is per topic, and a quiet topic is not in it.** One line per
keyword group - the group's name, then at most `SENTENCES_MAX` sentences about
what actually stood out. A group whose day held nothing notable is left out of
the prompt entirely rather than given a sentence saying so, which is what keeps
the message a glance. The rows arrive already `score DESC` from
`store._matches()`, so "the notable ones" is a slice and not a second ranking
pass.

**The page gets it every cycle; a phone gets it once a local day.** The page is
somewhere you go and a message is something that interrupts you, and
forty-eight interruptions a day saying roughly the same thing is how a channel
gets muted - taking the outage alerts of P6-2 with it. "Once" survives a restart
because it is not remembered in memory: the summary rides in the existing
`reported` table under `summarize.daily_key()`, per channel and idempotent, the
same mechanism that keeps a story from being sent twice.

**And it may never cost a cycle.** `summarize()` has exactly one failure mode,
`None`, and the caller adds nothing to `problems`. An endpoint having a bad
afternoon is a page without a paragraph - never a withheld heartbeat ping, and
never an ops alert. That asymmetry is deliberate in the same way P6-1's is: the
thing that is optional must not be able to speak for the thing that is not.

**What is left is time, not code.** Seven days unattended with no manual
intervention and no disk growth is P6's definition of done, and nothing has yet
run unattended for longer than a cycle. `progress.md` carries the clock.

## What is deliberately not in scope

- No multi-user accounts, no login, no write API — the page is read-only output.
- No comment scraping, no full-article extraction: titles, links, timestamps only.
- No mobile app; the page is responsive and that is the whole client story.
