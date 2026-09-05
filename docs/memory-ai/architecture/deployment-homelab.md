---
title: Homelab Deployment
category: architecture
purpose: How news-radar runs on the homelab and how https://news.dtbao.org reaches the outside world.
status: active
updated: 2026-09-05
source: docker/docker-compose.yml, docker/cloudflared.yml, docker/Caddyfile, scripts/setup.py
confidence: confirmed
keywords: news.dtbao.org, homelab, docker compose, caddy, cloudflared, cloudflare tunnel, tunnel profile, schedule, volumes, restart policy
order: 3
---

# Homelab Deployment

> Three containers on the homelab: one crawls on a loop and writes `output/`,
> one serves `output/` over HTTP, one carries that to `news.dtbao.org` through a
> Cloudflare Tunnel. Nothing is published from GitHub.

## Topology

```
            internet
               |
        Cloudflare edge          TLS terminates here
               |
   +-----------+-------------------------------------------------------------+
   |           |                                   docker network (homelab)  |
   |     cloudflared                 outbound-only, no port forwarding        |
   |           |  http://caddy:8080                                           |
   |           v                                                              |
   |   caddy  :8080  ---- reads ---->  output/  <---- writes ---- news-radar  |
   |   serves static files             (volume)                  (crawl loop) |
   |                                                            reads config/ |
   +--------------------------------------------------------------------------+
```

Only Caddy is reachable, and only from inside the network. The crawl container
exposes no port; it talks outward to the news sources, Telegram and Discord, and
nothing talks in to it. `cloudflared` exposes no port either - it dials the
Cloudflare edge outbound and the edge answers the public request over that
connection.

## Services

| Service | Image | Role | Ports |
|---------|-------|------|-------|
| `news-radar` | built from the repo `Dockerfile` | Crawl loop: fetch, filter, rank, store, render, notify | none |
| `caddy` | `caddy:2-alpine` | Serves `/srv` (the `output/` volume) as static files | `8080` inside the network; published on the host as `NEWS_RADAR_HTTP_PORT`, default `8088` |
| `cloudflared` | `cloudflare/cloudflared:2026.8.3` | Carries `news.dtbao.org` to `http://caddy:8080`. Behind the `tunnel` compose profile | none |

**The published host port is `NEWS_RADAR_HTTP_PORT`, default `8088`**, and it
exists only for local debugging: the tunnel talks to `caddy:8080` over the docker
network and ignores it entirely.

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
bearing now that P5 has put this on the public internet: verified 2026-09-05
against the live hostname, `https://news.dtbao.org/news.db` and
`https://news.dtbao.org/days/` both answer `404` while `/` answers `200`.

### The tunnel

`news.dtbao.org` is carried by a dedicated Cloudflare Tunnel named `news`
(`94fedb96-98c6-4683-8ae5-6addda3d9c9e`), whose connector runs **as a container
in this compose project**:

| Piece | Where | Committed |
|-------|-------|-----------|
| Ingress: `news.dtbao.org` -> `http://caddy:8080`, else `http_status:404` | `docker/cloudflared.yml` | yes - a tunnel id is not a secret |
| Connector credentials | `docker/tunnel-credentials.json`, mounted at `/etc/cloudflared/creds.json` | **no** - gitignored |
| The service itself | `docker/docker-compose.yml`, `profiles: ["tunnel"]` | yes |

**In the stack rather than on the host, for two reasons.** The origin can only
be the service name `caddy:8080` from inside the docker network - a connector
running on the host cannot resolve it, and would have to be pointed at the
published debug port instead. And a host connector is usually already carrying
other hostnames: this homelab runs one as a Windows service (`win-dev`) for
`ssh.dtbao.org` and `remote.dtbao.org`, so restarting it to change the news
route would drop the operator's own remote access.

**Behind a profile**, so `docker compose up -d` starts the crawl loop and the
web server and nothing else. The credentials file is not in the repo, and
without the profile a fresh clone would get a container crash-looping on a
missing bind mount. `scripts/setup.py` adds `--profile tunnel` on its own once
the file is there - see [[cli-scripts]].

The published host port therefore remains what it always was: local debugging.
Nothing outside the LAN reaches it.

## Volumes

| Host path | Container path | Mode | Holds |
|-----------|----------------|------|-------|
| `./config` | `/app/config` | read-only | `config.yaml`, `frequency_words.txt` |
| `./output` | `/app/output` | read-write (crawl) / read-only (caddy, as `/srv`) | `index.html`, `news.db`, per-day snapshots |
| `./docker/cloudflared.yml` | `/etc/cloudflared/config.yml` | read-only | the tunnel's ingress |
| `./docker/tunnel-credentials.json` | `/etc/cloudflared/creds.json` | read-only | the connector's credentials |

`output/` is a bind mount, not a named volume, so a human can open
`output/index.html` directly on the host to debug a render without touching the
container.

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
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | `docker/.env` | `notify/telegram.py` |
| `DISCORD_WEBHOOK_URL` | `docker/.env` | `notify/discord.py` |
| `TZ` | `docker/.env`, default `Asia/Ho_Chi_Minh` | timestamps on the page and in messages |
| `NEWS_RADAR_CONFIG` | compose, default `/app/config/config.yaml` | `config.py` |

`docker/.env` is gitignored and created by `scripts/setup.py`. See
[[config-and-env]] for the full key list.

## Failure modes to design for

| What breaks | Symptom | Where it is handled |
|-------------|---------|---------------------|
| One source is down or rate-limits | That source contributes nothing this run | `fetch/` isolates per-source failures (P1-5) |
| Tunnel drops | `news.dtbao.org` unreachable, crawl keeps working | Cloudflare reconnects; `restart: unless-stopped` covers a connector crash; `output/` is still correct on the host and on `NEWS_RADAR_HTTP_PORT` |
| Credentials file missing or wrong | `cloudflared` crash-loops, the site answers Cloudflare error `1033` | `docker compose ps` shows it restarting; the profile keeps a checkout without the file from ever starting it |
| Disk fills with snapshots | Writes fail | Retention window (P3-5, P6) |
| Crawl crashes on a bad item | Container exits | `restart: unless-stopped` plus a heartbeat so a crash loop is visible (P6-1) |
| Clock skew | Freshness ranking goes wrong | `TZ` pinned in the container, not inherited from the host |
