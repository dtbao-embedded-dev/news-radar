---
title: Homelab Deployment
category: architecture
purpose: How news-radar runs on the homelab and how https://news.dtbao.org reaches the outside world.
status: draft
updated: 2026-09-04
source: conversation
confidence: inferred
keywords: news.dtbao.org, homelab, docker compose, caddy, cloudflare tunnel, schedule, volumes, restart policy
order: 3
---

# Homelab Deployment

> Two containers on the homelab: one crawls on a loop and writes `output/`, one
> serves `output/` over HTTP. A Cloudflare Tunnel maps `news.dtbao.org` onto the
> second one. Nothing is published from GitHub.

## Topology

```
            internet
               |
        Cloudflare edge          TLS terminates here
               |
      Cloudflare Tunnel          outbound-only, no port forwarding
               |
   +-----------+-------------------------+   docker network (homelab)
   |                                     |
   |   caddy  :8080  ---- reads ---->  output/  <---- writes ---- news-radar
   |   serves static files              (volume)                 (crawl loop)
   |                                                             reads config/
   +-------------------------------------------------------------------------+
```

Only Caddy is reachable. The crawl container exposes no port; it talks outward to
the news sources, Telegram and Discord, and nothing talks in to it.

## Services

| Service | Image | Role | Ports |
|---------|-------|------|-------|
| `news-radar` | built from the repo `Dockerfile` | Crawl loop: fetch, filter, rank, store, render, notify | none |
| `caddy` | `caddy:2-alpine` | Serves `/srv` (the `output/` volume) as static files | `8080` on the docker network |

Add a `cloudflared` service only if the homelab does not already run a tunnel.
It already serves `mcp.dtbao.org`, so the cheaper path is to add one public
hostname route to the existing tunnel, pointing `news.dtbao.org` at
`http://caddy:8080`.

## Volumes

| Host path | Container path | Mode | Holds |
|-----------|----------------|------|-------|
| `./config` | `/app/config` | read-only | `config.yaml`, `frequency_words.txt` |
| `./output` | `/app/output` | read-write (crawl) / read-only (caddy, as `/srv`) | `index.html`, `news.db`, per-day snapshots |

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
| Tunnel drops | `news.dtbao.org` unreachable, crawl keeps working | Cloudflare reconnects; `output/` is still correct on the host |
| Disk fills with snapshots | Writes fail | Retention window (P3-5, P6) |
| Crawl crashes on a bad item | Container exits | `restart: unless-stopped` plus a heartbeat so a crash loop is visible (P6-1) |
| Clock skew | Freshness ranking goes wrong | `TZ` pinned in the container, not inherited from the host |
