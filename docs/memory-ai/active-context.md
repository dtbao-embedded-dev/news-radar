---
title: Active Context
updated: 2026-09-05
---

# Active Context

> What is being worked on right now. Read first every session; rewrite when the focus shifts. Transient - not a durable fact.

## Current focus

**P4 Notify is done** (2026-09-05). A cycle that finds something new now pushes
it to Telegram and Discord instead of only writing the page. Measured live in
the container: the first `--once` after the rebuild sent **2 Telegram messages
and 5 Discord messages carrying the same 43 stories**, and the `--once` run
straight after it printed `nothing new to send` on both channels and sent
nothing. That is the phase's definition of done, both halves of it.

The next piece of work is **P5 Deploy**: the Cloudflare Tunnel route for
`news.dtbao.org` and the first unattended live run. The `Dockerfile`, the
compose stack and the schedule loop are already done, so P5 is mostly network
configuration outside this repository.

## Recent changes

- **P4 landed in eight commits on `release/v0.1`** (2026-09-05):
  `fetch/http.py` (`post_json()`, `Retry-After`), `store.py` (`run_matches()`),
  `notify/__init__.py` (`SendResult`, `pick`, `chunk`, `clip`),
  `notify/telegram.py`, `notify/discord.py`, and `_notify()` in `__main__.py`.
- **The senders read the store, not `ranked`** - the same choice P3 made for the
  page, for the same reason. The story that goes out carries the same score and
  the same source list as the one on the page, and `report.mode` only changes
  *which window* is read: `run_matches()` for `incremental` and `current`,
  `day_matches()` for `daily`.
- **`report.mode` finally does something.** It was validated by `config.py` from
  P0 onward and read by nothing; `mode: daily` was accepted and silently
  ignored. All three modes now behave as the config comment claims.
- **The transport learned to POST, and learned to read `Retry-After`.** Both
  changes live in `Fetcher` rather than in `notify/`, so the GET path gets the
  429 fix too - Google News throttles as readily as a bot API does.
- **One deliberate widening of the layering rule**: `notify/*` imports layer 1.
  Recorded in [[module-layout]] and [[notify-channels]] rather than left to be
  discovered.
- **Two departures from the drafted contract, both recorded in
  [[notify-channels]]**: `send()` takes no `RunMeta` (nothing consumed it), and
  the secrets are read in `__main__` rather than inside each channel (which is
  what lets both channels be tested with no environment at all).

Before this session: P3 landed the store and the page, P2 the selection layer,
P1 the whole fetch layer, P0 the release tooling, the docker stack, the config
loader and the design bank - see `progress.md`.

## Next steps

1. **P5-3 Cloudflare Tunnel route** for `news.dtbao.org` to `caddy:8080`.
2. **P5-4 first unattended live run**, verified from outside the LAN.
3. **Watch the messages for a few days.** Two things are worth eyeballing that
   no test can assert: whether 5 Discord messages per cycle is pleasant or
   noisy, and whether any real headline trips an escaping case the fixtures
   missed.
4. **Retention has still never run against a window with anything to drop** -
   `retention_days` is `0` in the shipped config, so nothing prunes until
   someone sets it.

## Active decisions

- **A story is marked sent only after the message carrying it was accepted.** A
  crash between the send and the write re-sends next cycle; a duplicate is the
  acceptable failure where a silently dropped story is not. `mark_reported()`
  after the sender returns, never before.
- **A refusal ends the channel for that run.** The same answer is coming for
  chunk two, and hammering a throttled bot is how throttled becomes banned.
  Whatever was accepted before the refusal still counts as sent.
- **Two guards around notification, and both are needed.** The outer one keeps a
  locked store from costing the page; the inner one is per channel, because the
  contract says a dead webhook must leave the other channel still attempted.
- **The page is rendered from the store, not from `ranked`.** A
  `render.write(..., ranked)` anywhere is a bug, not a shortcut.
- **Layer 3 and layer 4 import no config and read no clock.** The weights, the
  `{source_id: rank_weight}` map, the data directory, the retention window and
  `now` are all arguments `__main__.py` builds. It is why ten of the twelve test
  files run with nothing installed.
- **Everything off a feed is escaped at the boundary it is crossing.** The page
  escapes for HTML, Telegram for its own HTML subset, Discord for Markdown - and
  the three sets of dangerous characters are not the same one. A feed title is
  somebody else's text arriving unreviewed every thirty minutes.
- **The page needs no network to be read.** Inline CSS and JavaScript, no
  external stylesheet, script or image - `test_render.py` asserts it rather than
  trusting it.
- **Clean-room from TrendRadar.** It is a reference to consult when stuck, never
  a source to copy from - it is GPL-3.0. `rule/reference-trendradar.md` says
  where to look by problem and what may not cross back.
- **Two runtime dependencies, total**: `pyyaml` and `feedparser`. HTTP, storage,
  templating and both senders come from the standard library. A third needs
  justifying in the changelog. P4 held the line - the channels are `urllib` and
  `json`.
- **One guard, not one per caller.** `feeds.read_source()` is the only place a
  source failure is caught; `_publish()` the only place a storage or render
  failure is; `_notify()` the only place a send failure is.
- **The changelog records technical changes only**, written by hand into
  `## Unreleased` in the same commit as the change. One entry per change, not
  per commit: all of P4 is one `**crawl**` line.
- **Both scripts stay stdlib-only** so they run on a bare checkout, before
  anything is installed.
- **Self-hosted, not GitHub Pages.** The crawl and the site both run on the
  homelab; `news.dtbao.org` is reached through the existing Cloudflare Tunnel.
- **Secrets live only in `docker/.env`.** `config.yaml` is committed as a
  template and a leaked copy must be harmless.
