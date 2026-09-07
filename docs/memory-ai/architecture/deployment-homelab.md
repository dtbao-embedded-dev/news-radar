---
title: Homelab Deployment
category: architecture
purpose: How news-radar runs on the homelab, what serves the report, and why nothing in the stack carries it off the LAN.
status: active
updated: 2026-09-07
source: docker/docker-compose.yml, docker/Caddyfile, docker/.env.example, .github/workflows/image.yml, scripts/setup.py
confidence: confirmed
keywords: homelab, LAN only, published nowhere, no tunnel, docker compose, caddy, NEWS_RADAR_HTTP_PORT, 8088, autoupdate profile, watchtower, ghcr, image, NEWS_RADAR_HOME, NEWS_RADAR_VERSION, WATCHTOWER_POLL_INTERVAL, schedule, volumes, restart policy
order: 3
---

# Homelab Deployment

> Two containers on the homelab: one crawls on a loop and writes `output/`, one
> serves `output/` over HTTP on the LAN. A third, off by default, updates the
> first. **Nothing in this stack carries the report off the LAN** - where it is
> reachable from is a decision made outside the project.

## Topology

```
       a reader on the LAN
               |
               |  http://<host>:8088          NEWS_RADAR_HTTP_PORT
   +-----------+-------------------------------------------------------------+
   |           v                                 docker network (homelab)    |
   |   caddy  :8080  ---- reads ---->  output/  <---- writes ---- news-radar  |
   |   serves static files             (volume)                  (crawl loop) |
   |                                                            reads config/ |
   +--------------------------------------------------------------------------+
                                                       |
                                    outbound only ---->+---> feeds, Telegram,
                                                             Discord, GHCR
```

Caddy's published port is the only way in, and it reaches no further than the
LAN. The crawl container exposes no port at all; it talks outward to the news
sources, Telegram and Discord, and nothing talks in to it.

**Putting the report on the internet is deliberately not this project's job.**
There was a Cloudflare Tunnel here until it was removed - see [[progress]] - and
what replaced it is nothing. A reverse proxy, a tunnel, a VPN or no access at
all are all choices to make in front of the published port, and each of them
would otherwise be a permanent moving part in a stack whose actual job is to
write HTML into a directory.

## Services

| Service | Image | Role | Ports |
|---------|-------|------|-------|
| `news-radar` | `ghcr.io/dtbao-embedded-dev/news-radar:${NEWS_RADAR_VERSION:-latest}`, or built from the repo `Dockerfile` | Crawl loop: fetch, filter, rank, store, render, notify | none |
| `caddy` | `caddy:2-alpine` | Serves `/srv` (the `output/` volume) as static files | `8080` inside the network; published on the host as `NEWS_RADAR_HTTP_PORT`, default `8088` |
| `watchtower` | `containrrr/watchtower:1.7.1` | Polls GHCR and recreates `news-radar` on a newer `:latest`. Behind the `autoupdate` compose profile | none |

**The crawl service carries both `image:` and `build:`, deliberately.** Compose
builds only when the image is absent locally, so a checkout compiles what it is
editing and a deployment - where `pull` has already fetched the image - never
builds. The cost is one footgun: `up -d` before `pull` on a deployment tries to
build and dies on the absent `Dockerfile`. The gain is one compose file instead
of two that can disagree, and `tests/test_deploy.py` pins its shape.

**One profile, opt-in.** `autoupdate` would, on a development machine, pull
`:latest` from GHCR straight over the image the developer just built, so
production is the only place it belongs:

```
docker compose --profile autoupdate up -d
```

`--profile tunnel` still parses and starts nothing extra - the service it named
is gone - so an old command in somebody's shell history is harmless rather than
confusing.

**Watchtower touches exactly one container.** `news-radar` is the only service
labelled `com.centurylinklabs.watchtower.enable`, and `WATCHTOWER_LABEL_ENABLE`
makes that label the filter - without it watchtower updates every container on
the host. caddy is `2-alpine` rather than a digest, and an unreviewed upgrade of
the one thing serving the report is not something to find out about from a
changed page. The `:ro` on its docker socket mount
is **not** a sandbox - a socket is a socket, and every API call still goes
through; access to it is root on the host. The narrowing is the label and the
profile.

**The published host port is `NEWS_RADAR_HTTP_PORT`, default `8088`**, and it is
now the only way to reach the report at all - it used to be described as
debugging-only, back when a tunnel carried the real traffic.

`8088` was originally forced - ntfy held `127.0.0.1:8080` on this homelab, so
binding `8080` failed with `port is already allocated` and a probe of
`localhost:8080` silently answered from ntfy. That container was removed on
2026-09-05 and `8080` is free again, but the default stays `8088` **by choice**:
a port of our own does not have to be renegotiated the next time something else
on the homelab wants the obvious one. Verified 2026-09-05 - Caddy answers `200`
on `8088` with the `Cache-Control` headers from our Caddyfile, and nothing
listens on `8080`.

### What Caddy will and will not serve

`output/` is one volume holding the pages **and** the SQLite store, so the file
server has to be told the difference:

| Path | Answer |
|------|--------|
| `/`, `/index.html` | the current report, `Cache-Control: no-cache` |
| `/days/<date>.html` | that day's snapshot, `Cache-Control: public, max-age=3600` |
| `/news.db`, `/news.db-wal`, `/news.db-shm`, `/news.db-journal` | `404` |
| any directory | `404` - `browse` is off |

The store is not part of the report: serving it hands a stranger the whole
archive in one request. `404` rather than `403`, because there is no reason to
confirm the file is there. Directory listing is off for the same reason and
costs nothing - `index.html` already links every snapshot. Both rules are load
bearing whatever fronts the published port: verified 2026-09-05 against the
public hostname the project had at the time - `/news.db` and `/days/` both
answered `404` while `/` answered `200`. That hostname is gone with the tunnel,
but the Caddyfile rules are unchanged and are what a future reverse proxy would
be relying on.

## Volumes

Every path a deployment owns is resolved from **one** variable,
`NEWS_RADAR_HOME`, relative to the compose file. Unset it is `..`, which on a
checkout is the repository root - exactly where those directories already are,
so a checkout behaves as it always did. A deployment sets it to `.` and keeps
its data beside the compose file, on a machine with no git checkout at all.

| Host path | Container path | Mode | Holds |
|-----------|----------------|------|-------|
| `${NEWS_RADAR_HOME:-..}/config` | `/app/config` | read-only | `config.yaml`, `frequency_words.txt` - both the deployment's own, neither ever written by an update |
| `${NEWS_RADAR_HOME:-..}/output` | `/app/output` | read-write (crawl) / read-only (caddy, as `/srv`) | `index.html`, `news.db`, per-day snapshots |
| `${NEWS_RADAR_HOME:-..}/backups` | `/app/backups` | read-write | dated copies of the store. Crawl service only - caddy never sees the path |
| `./Caddyfile` | `/etc/caddy/Caddyfile` | read-only | the static-file config |
| `/var/run/docker.sock` | same | see above | watchtower's only mount |

**The two prefixes are not interchangeable.** `${NEWS_RADAR_HOME:-..}` is the
deployment's data; `./` is a file that ships beside the compose file and is the
same file in both layouts. Giving `Caddyfile` the variable would send a flat
deployment looking for `./config/Caddyfile`.

**Caddy's `/srv` moves with `output/`.** It is the one mount easy to leave
behind, and leaving it behind has the crawl publish to one directory while the
web server serves another - the site 404s while every log line in the crawl says
success.

`output/` is a bind mount, not a named volume, so a human can open
`output/index.html` directly on the host to debug a render without touching the
container. Because they are bind mounts, a container recreate - which is what
both a manual update and watchtower do - re-attaches them exactly as they were.
Measured on the homelab: a forced recreate left `config/config.yaml` and
`output/news.db` byte-identical by `sha256sum`, with the container id genuinely
changed.

## Scheduling

The crawl container runs a **loop inside the process**, sleeping
`schedule.interval_minutes` (default 30) between runs. It is not a cron job.

Reasons: Compose has no scheduler; a host cron is written differently on Windows
and Linux, which breaks the "same three steps on both" promise; and an in-process
loop keeps the SQLite connection and the seen-set warm between runs.

Consequences to accept: the container must be restarted for a config change to
take effect, and `restart: unless-stopped` is what makes a crash recover. A run
that hangs must be bounded by the HTTP timeouts in `fetch/http.py`, because
nothing outside the process will kill it.

## Environment

| Variable | Set in | Used by |
|----------|--------|---------|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | `.env` | `notify/telegram.py` |
| `DISCORD_WEBHOOK_URL` | `.env` | `notify/discord.py` |
| `TZ` | `.env`, default `Asia/Ho_Chi_Minh` | timestamps on the page and in messages |
| `NEWS_RADAR_CONFIG` | compose, default `/app/config/config.yaml` | `config.py` |
| `NEWS_RADAR_HOME` | `.env`, default `..` | compose only - the three data bind mounts |
| `NEWS_RADAR_VERSION` | `.env`, default `latest` | compose only - which published image to run |
| `NEWS_RADAR_HTTP_PORT` | `.env`, default `8088` | compose only - caddy's host port |
| `WATCHTOWER_POLL_INTERVAL` | `.env`, default `86400` | compose only - watchtower, when its profile is on |

`.env` sits beside the compose file - `docker/.env` in a checkout, where
`scripts/setup.py` creates it, and the deployment root otherwise. It is never
committed. The last four are read by Compose during substitution, not by any
Python in this project. See [[config-and-env]] for the full key list.

## Failure modes to design for

| What breaks | Symptom | Where it is handled |
|-------------|---------|---------------------|
| One source is down or rate-limits | That source contributes nothing this run | `fetch/` isolates per-source failures (P1-5) |
| Whatever fronts the published port breaks | The report is unreachable from wherever the reader is, crawl keeps working | **Not handled here, on purpose** - there is nothing in this stack between Caddy and the reader. `output/` stays correct on disk and on `NEWS_RADAR_HTTP_PORT`, and `ops.site_url` pointed at `http://caddy:8080/` still passes, because from inside the network nothing is wrong |
| Caddy stops serving | The report is unreachable and the crawl cannot tell | `ops.site_url: http://caddy:8080/` fetches it every cycle, so a dead web server withholds the heartbeat ping and counts as a failed cycle |
| Disk fills with snapshots | Writes fail | Retention window (P3-5, P6) |
| Crawl crashes on a bad item | Container exits | `restart: unless-stopped` plus a heartbeat so a crash loop is visible (P6-1) |
| Clock skew | Freshness ranking goes wrong | `TZ` pinned in the container, not inherited from the host |
| Auto-update lands a release whose **cycles** fail | Every cycle reports problems, the process stays up | `ops.Health` reaches `ALERT_AFTER` and one message goes out on the second cycle, one more on recovery |
| Auto-update lands a release that **will not start** | Container exits `1` and `restart: unless-stopped` loops it | **Nothing is sent.** `main()` returns before `run()` builds `ops.Health` (`__main__.py:611` vs `:563`), and each restart is a fresh process, so the counter never reaches two. Measured: 9 restarts in 45 s, zero `starting` lines, zero health lines. Only the dead-man's switch covers this - and `ops.heartbeat_url` ships empty, so today it is covered by nothing. Roll back with `NEWS_RADAR_VERSION=<previous>` in `.env` plus `up -d` |
| GHCR unreachable at poll time | Nothing updates | Watchtower logs it and retries at the next interval; the running container is untouched, so an unreachable registry costs nothing |
| `NEWS_RADAR_HOME` set to a path that does not exist | Docker **creates** it, as `root`, and the container gets empty directories | Loud, not silent: `config file not found: /app/config/config.yaml`, exit `1`, restart loop. But it also leaves root-owned directories on the host that the operator cannot `rm` without `sudo` - measured |
