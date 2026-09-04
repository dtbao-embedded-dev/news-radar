---
title: Setting Up on the Homelab
category: rule
purpose: The procedure from a fresh clone to news.dtbao.org serving, identical on Windows and Linux.
status: active
updated: 2026-09-04
source: scripts/setup.py, docker/docker-compose.yml, docker/Caddyfile
confidence: confirmed
keywords: setup, setup.py, docker compose, homelab, cloudflare tunnel, news.dtbao.org, .env, config.yaml, NEWS_RADAR_HTTP_PORT, 8088
order: 2
---

# Setting Up on the Homelab

> Three steps: clone, `python scripts/setup.py`, `docker compose up -d`. The
> same three on Windows and on Linux - that is why setup is a Python script and
> not a pair of shell scripts.

## Prerequisites

| Needs | Why |
|-------|-----|
| Python 3.11+ | Runs `setup.py` and `release.py`; `setup.py` checks the version and refuses an older one |
| Docker Engine + Compose v2 | Runs the stack. `setup.py` reports both versions before doing anything else |
| A free host port | `8080` is already taken on this homelab by ntfy - the default published port is `8088`, overridable with `NEWS_RADAR_HTTP_PORT` |

Nothing else. There are no API keys for fetching news; every secret is a
notification secret.

## Procedure

```
git clone git@github.com:dtbao-embedded-dev/news-radar.git
cd news-radar
python scripts/setup.py
docker compose -f docker/docker-compose.yml up -d
```

**Step 2 in detail.** `setup.py` checks Python and Docker, then creates the two
files that are deliberately not in git:

| Created | From | Holds |
|---------|------|-------|
| `config/config.yaml` | `config/config.yaml.example` | Feeds, search templates, ranking weights, schedule |
| `docker/.env` | `docker/.env.example` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DISCORD_WEBHOOK_URL`, `TZ`, `NEWS_RADAR_HTTP_PORT` |

It then asks for any notification secret that is still empty and writes it into
`docker/.env`, preserving the comments. It **exits non-zero while a required
secret is blank** - a stack that starts and silently never notifies is the
failure this project most wants to avoid.

An existing file is never overwritten: it is reported as `[skip]`. Use `--force`
to replace one deliberately.

| Flag | Use it when |
|------|-------------|
| `--dry-run` | You want to see what it would do. Writes nothing, asks nothing |
| `--check` | Verifying an existing install - same checks, creates nothing |
| `--force` | Regenerating a config from the template on purpose |
| `--non-interactive` | Unattended provisioning; a blank secret is reported, not prompted for |

## Getting the secrets

- **Telegram** - create a bot with `@BotFather` for the token. Message the bot
  once, then read the chat id from
  `https://api.telegram.org/bot<TOKEN>/getUpdates`.
- **Discord** - channel settings, Integrations, Webhooks, New Webhook, Copy URL.

Both live only in `docker/.env`, which is gitignored. They never go into
`config.yaml`.

## Exposing news.dtbao.org

Caddy serves `output/` inside the docker network on port `8080`. The published
host port (`8088` by default) is for local debugging only.

The homelab already runs a Cloudflare Tunnel for `mcp.dtbao.org`, so the cheap
path is to add one public hostname to it rather than run a second tunnel:

| Field | Value |
|-------|-------|
| Public hostname | `news.dtbao.org` |
| Service | `http://caddy:8080` |

The tunnel container must be on the same docker network as `caddy` for that
service name to resolve. If it lives in another compose project, attach it to
this project's network as an external network rather than publishing more ports.

## Verifying it works

1. `docker compose -f docker/docker-compose.yml ps` - both services `running`.
2. `curl http://localhost:8088/` - Caddy answers with the current report.
   A 200 from a *different* service means the port is taken; change
   `NEWS_RADAR_HTTP_PORT` rather than guessing.
3. Open `https://news.dtbao.org` from outside the LAN.
4. Wait one `schedule.interval_minutes` and check that Telegram and Discord each
   received exactly one message.

## Updating

```
git pull
python scripts/setup.py --check
docker compose -f docker/docker-compose.yml up -d --build
```

`--check` catches a config key added upstream that the local `config.yaml` does
not have yet. The crawl container reads its config at startup, so a config change
needs a restart - see [[deployment-homelab]].
