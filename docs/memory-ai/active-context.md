---
title: Active Context
updated: 2026-09-05
---

# Active Context

> What is being worked on right now. Read first every session; rewrite when the focus shifts. Transient - not a durable fact.

## Current focus

**P6 Ops is built** (2026-09-05). A cycle that fails now says so - twice per
outage, on Telegram and Discord - and a cycle that stops happening at all trips a
dead-man's switch that lives outside this stack. The store gets a dated backup
before anything is pruned, and the archive has a 90-day ceiling.

**What is left of P6 is time, not code.** Seven days unattended with no manual
intervention and no disk growth is the phase's definition of done, and the clock
starts when this branch merges.

## Recent changes

- **P6 landed in twenty-one commits on `release/v0.1`** (2026-09-05):
  `src/news_radar/ops.py` (new - `heartbeat()`, `Health`, `ALERT_AFTER`),
  `store.py` (`backup()`), `notify/telegram.py` and `notify/discord.py`
  (`alert()`), `__main__.py` (`crawl()` returns `(ranked, problems)`,
  `_dead_sources()`, `ALERTERS`, `_alert()`), `config.py` (the `ops` section),
  `config/config.yaml.example`, `docker/docker-compose.yml`, `.gitignore`,
  `Dockerfile`, and `tests/test_ops.py` (new).
- **A ping is a claim that the cycle worked**, and that one sentence decided the
  whole shape of P6-1. The published page is fetched *before* the ping and any
  problem anywhere withholds it, so silence is the signal - which is the only
  thing that can survive the container being killed.
- **The site check is what closes the tunnel gap.** `progress.md` had carried
  "nothing yet alerts on it" as a known issue since P5; the crawl now fetches
  `https://news.dtbao.org/` every cycle, so a connector that deregistered is a
  failed cycle rather than something you find out about days later.
- **Two messages per outage, not one every thirty minutes.** `ALERT_AFTER = 2`
  and the recovery message are the whole of `ops.Health`. An alert that repeats
  alongside the thing it is reporting is one you learn to swipe away, and the
  next real one goes with it.
- **The live run found a hole the tests could not.** A *successful* alert logged
  nothing at all - the only trace in `docker logs` was an unexplained two-second
  gap. `_alert()` now logs `alerted N of M channel(s)` at WARNING, which is also
  what proved both channels accepted the message.
- **`backups/` is outside `output/`, not merely excluded from it.** Caddy roots
  on `output/`; a dated copy of the whole archive there would be one Caddyfile
  line from public. The bind mount is on the crawl service only.
- **The retention default and the retention template deliberately disagree.**
  `config.py` keeps `0` so an upgrade never starts deleting rows nobody chose to
  lose; the shipped template says `90` because someone chose it.
- **P6-4 (AI summary) was dropped on its own terms** - the only planned task that
  serves none of the six finished-product statements, against an API key and a
  third runtime dependency. Recorded in [[delivery-phases]] rather than deleted.
- **P5 landed in four commits on `release/v0.1`** (2026-09-05):
  `docker/cloudflared.yml` (new, the ingress), `docker/docker-compose.yml` (the
  `cloudflared` service behind `profiles: ["tunnel"]`), `.gitignore`,
  `scripts/setup.py` (`compose_argv()` takes a `root` and detects the
  credentials file), `tests/test_setup.py` (new).
- **The bank was wrong about the tunnel and P5 corrected it.** It described a
  tunnel *container* the homelab already ran for `mcp.dtbao.org`, to be attached
  to this project's network. Reality: cloudflared runs here as the Windows
  service `win-dev`, carrying `ssh.dtbao.org` and `remote.dtbao.org`. A host
  connector cannot resolve `caddy`, so the connector had to move into the stack
  for the documented `http://caddy:8080` origin to exist at all.
- **The route was already there; the connector was not.** `news.dtbao.org` was
  a DNS record pointing at a tunnel named `news` that had never been run - the
  site answered Cloudflare `1033`. All of P5-3 was starting the container.
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

1. **Point `ops.heartbeat_url` at a real monitor.** It ships empty, so the half
   of P6-1 that survives the container being killed is built but not armed. A
   healthchecks.io ping url or an Uptime Kuma push url in `config/config.yaml`
   (gitignored) is the whole change - no code, no restart of anything else.
2. **Let it run seven days.** That is P6's definition of done and the only thing
   still open. On day seven: the crawl container still `Up` with no restart,
   `backups/` holding one file per day and no more, the day list capped at 90,
   and however many alerts arrived being ones you would have wanted.
3. **Watch whether `ALERT_AFTER = 2` is the right chattiness.** Every alert so
   far came from a `site_url` pointed at a 404 on purpose; real feed flakiness
   has not been through it yet.
4. **Retention will actually delete something for the first time** once the
   store holds anything older than 90 days. A backup is written immediately
   before each prune, so the first one has a copy standing in front of it.
5. **Still worth eyeballing from P4**: whether 5 Discord messages per cycle is
   pleasant or noisy, and whether any real headline trips an escaping case the
   fixtures missed.

## Active decisions

- **A ping is a claim that the cycle worked.** It is never made before the
  published page has answered, and any problem anywhere in the cycle withholds
  it. A heartbeat that fires regardless of outcome is worse than none: it
  actively reports health that is not there.
- **Silence is the signal, and it has to be read from outside.** A killed
  container, a host that lost power and a daemon that never came back are
  indistinguishable from inside the process. That is why P6-1 is a dead-man's
  switch rather than an internal check.
- **A refused ping is a warning, never an alert.** The radar is fine and the
  thing that would have told you so is what broke. Alerting on it is how you
  train yourself to ignore the alert.
- **Two messages per outage, whatever its length** - one at `ALERT_AFTER = 2`
  consecutive failures, one on the first clean cycle after. `Health` lives in
  memory and dies with the process on purpose: a container that restarted has
  lost the context that made the first alert true, and re-arming means a
  crash-looping stack says so again rather than going quiet forever.
- **No backup, no deletion.** `store.backup()` runs immediately before
  `store.prune()` inside the same guard, so a store that cannot be copied is
  never pruned.
- **`ops.backup_dir` is never under `storage.data_dir`.** Caddy roots on that
  directory; a dated copy of the whole archive in it would be one Caddyfile line
  from public. `store.py` cannot enforce this - it does not know what is being
  served - so it is a config rule.
- **A default is what an *absent* key falls back to, and must be the harmless
  value.** `storage.retention_days` defaults to `0` and the template ships `90`:
  an upgrade that never mentioned the key must not start deleting rows nobody
  chose to lose. The same rule flushed four wrong Default-column rows out of
  `config-and-env` when it was verified.
- **No `HEALTHCHECK` in the Dockerfile, deliberately.** It would only colour a
  column in `docker ps` - nothing restarts an unhealthy container without an
  autoheal sidecar, and that is a new moving part for a failure this stack has
  not had.
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
  homelab; `news.dtbao.org` is reached through a Cloudflare Tunnel whose
  connector is a container **in this stack**, not on the host. A host connector
  cannot resolve `caddy`, and restarting one that carries other hostnames costs
  those too.
- **A tunnel id is not a secret, a credentials file is.**
  `docker/cloudflared.yml` is committed; `docker/tunnel-credentials.json` is
  gitignored. The `tunnel` compose profile keeps a checkout without that file
  from ever starting the connector.
- **Secrets live only in `docker/.env`.** `config.yaml` is committed as a
  template and a leaked copy must be harmless.
