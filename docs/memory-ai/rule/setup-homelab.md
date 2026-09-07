---
title: Setting Up on the Homelab
category: rule
purpose: The procedure from nothing to a deployment serving the report on the LAN, and to a development checkout.
status: active
updated: 2026-09-07
source: docker/docker-compose.yml, docker/.env.example, docker/Caddyfile, .github/workflows/image.yml, scripts/setup.py, src/news_radar/__main__.py
confidence: confirmed
keywords: deployment directory, NEWS_RADAR_HOME, NEWS_RADAR_VERSION, ghcr, image, docker compose pull, ghcr private, package visibility, watchtower, autoupdate profile, --check, setup, setup.py, homelab, LAN only, published nowhere, no tunnel, reverse proxy, .env, config.yaml, NEWS_RADAR_HTTP_PORT, 8088
order: 2
---

# Setting Up on the Homelab

> A **deployment** runs the published image and keeps no source. A **checkout**
> is for developing. They share one `docker-compose.yml`, told apart by a single
> variable, so there is no second file to drift. Updating one, and migrating an
> existing checkout into one, is [[updating-homelab]].

## Two ways to run it

| | Deployment (production) | Checkout (development) |
|---|---|---|
| What it holds | compose file, `.env`, and the deployment's own data | the whole repository |
| `NEWS_RADAR_HOME` | `.` - data beside the compose file | unset (`..`) - data at the repo root |
| Crawl image | pulled from GHCR | built from the local `Dockerfile` |
| Install | `docker compose pull && up -d` | `python scripts/setup.py` |
| Update | `docker compose pull && up -d`, or watchtower - see [[updating-homelab]] | `git pull`, rebuild |
| Git | **none** | yes |

**The absence of git on a deployment is the design, not a shortcut.** A tracked
file a deployment edits cannot survive `git checkout <tag>`, and it fails in
whichever of two ways is worse for you: untouched it is **deleted**, edited the
checkout **aborts** and the upgrade stops. This project has already been on the
wrong side of that once (`config/frequency_words.txt`, v0.2.2). A machine with no
checkout has no command that can do either to `config/`, `output/` or
`backups/`.

## Prerequisites

| Needs | Deployment | Checkout |
|-------|-----------|----------|
| Docker Engine + Compose v2 | yes | yes |
| Python 3.11+ | **no** | yes - runs `setup.py` and `release.py` |
| A free host port | `8088` by default, `NEWS_RADAR_HTTP_PORT` overrides it | same |

There are no API keys for fetching news; every secret is a notification secret.

## Installing a deployment

The deployment directory is flat: the compose file and the three files beside it
come from the release, everything else is yours and nothing ever overwrites it.

```
~/news-radar/
  docker-compose.yml         from the release
  Caddyfile                  from the release
  .env                       yours - secrets, and NEWS_RADAR_HOME=.
  config/config.yaml         yours
  config/frequency_words.txt yours
  output/                    yours - the store and the published pages
  backups/                   yours - dated copies of the store
```

```
mkdir -p ~/news-radar/config ~/news-radar/output ~/news-radar/backups
cd ~/news-radar
BASE=https://raw.githubusercontent.com/dtbao-embedded-dev/news-radar/v<version>
curl -fsSLO "$BASE/docker/docker-compose.yml"
curl -fsSLO "$BASE/docker/Caddyfile"
curl -fsSL  "$BASE/docker/.env.example"                  -o .env
curl -fsSL  "$BASE/config/config.yaml.example"           -o config/config.yaml
curl -fsSL  "$BASE/config/frequency_words.txt.example"   -o config/frequency_words.txt
```

Then edit `.env`. Two things it will not work without:

- the notification secrets - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
  `DISCORD_WEBHOOK_URL`. The crawl **refuses to start** while an enabled channel
  has none: a stack that runs and silently never notifies is the failure this
  project most wants to avoid.
- **`NEWS_RADAR_HOME=.`** - without it the compose default is `..`, and the
  container mounts the directory *above* the deployment.

```
docker compose pull
docker compose --profile autoupdate up -d
docker compose run --rm news-radar --check
```

**The report is now reachable on `http://<host>:8088` and nowhere else.** There
is no tunnel and no reverse proxy in this stack - see the section below.

**The GHCR package came out public, and no login was needed.** This file used
to say the opposite - that a workflow-published package is private and the
`pull` would answer `denied` - on the strength of a documentation summary rather
than a test. Measured on the first real publish: the homelab pulled
`:0.2.3` with **no `~/.docker/config.json` at all**, and an anonymous registry
token fetched the manifest with `HTTP 200`.

If a future publish *is* private, the symptom is `denied` on `pull` and the fix
is one click - the package's page under the repository's **Packages**, Package
settings, Change visibility, Public. Prefer that to
`docker login ghcr.io` with a read:packages token, which puts a credential on
the deployment for no benefit.

**`pull` first, always.** The compose file carries `image:` and `build:` both,
and `up` **does not fall back to pulling** - measured, it goes straight to the
build and fails:

```
failed to solve: failed to read dockerfile: open Dockerfile: no such file or directory
```

That error on a deployment means the pull was skipped, not that anything is
broken. Pull, then `up -d`, and nothing builds again.

## Installing a checkout

Unchanged, and still two steps:

```
git clone git@github.com:dtbao-embedded-dev/news-radar.git
cd news-radar
python scripts/setup.py
```

`setup.py` checks Python and Docker, creates the three files that are
deliberately not in git, asks for any notification secret still empty, and then
starts the stack itself.

| Created | From | Holds |
|---------|------|-------|
| `config/config.yaml` | `config/config.yaml.example` | Feeds, search templates, ranking weights, schedule |
| `config/frequency_words.txt` | `config/frequency_words.txt.example` | The keyword groups |
| `docker/.env` | `docker/.env.example` | The secrets, `TZ`, `NEWS_RADAR_HTTP_PORT`, `NEWS_RADAR_HOME`, `NEWS_RADAR_VERSION` |

An existing file is never overwritten; it is reported as `[skip]`. `--force`
replaces one deliberately. Leave `NEWS_RADAR_HOME` empty here - the compose
default `..` is already the repo root. Its four flags and what each guarantees
are in [[cli-scripts]], which is where that contract lives.

## Getting the secrets

- **Telegram** - create a bot with `@BotFather` for the token. Message the bot
  once, then read the chat id from
  `https://api.telegram.org/bot<TOKEN>/getUpdates`.
- **Discord** - channel settings, Integrations, Webhooks, New Webhook, Copy URL.

Both live only in `.env`, never in `config.yaml`.

## Reaching it from outside the LAN

**Nothing in this stack does that, deliberately.** Caddy serves the
deployment's `output/` on port `8080` inside the docker network, published on the
host as `NEWS_RADAR_HTTP_PORT` (default `8088`). That port is the whole of the
project's answer.

There used to be a `cloudflared` service here carrying a public hostname. It was
removed: a connector is a permanent moving part, with its own credentials, its
own failure mode (Cloudflare `1033` while every other log line says success) and
its own upgrade story - all of that inside a project whose actual job is to write
HTML into a directory. Whatever you put in front of the published port is a
choice you can change without touching this repository, which is the point.

If you do front it, three things this project already does are worth keeping:

- **`docker/Caddyfile` answers `404` for `/news.db*` and for directory
  listings.** The store is not part of the report, and serving it hands a
  stranger the whole archive in one request. Those rules are what a proxy would
  be relying on - see [[deployment-homelab]].
- **`ops.site_url` should stay `http://caddy:8080/`**, not the public name. It
  runs inside the compose network, so it tests the thing this stack is
  responsible for; a public URL would make somebody else's outage into a failed
  cycle and withhold the heartbeat ping for it.
- **The archive is public the moment the port is.** Every
  `output/days/*.html` ever written is readable by anyone who can reach it, and
  there is no auth in this stack at all.

## Verifying it works

1. `docker compose ps` - `news-radar` and `caddy` running, plus `watchtower`
   when its profile is on. A service missing from the listing without its
   profile is the profile working, not a fault.
2. `curl http://localhost:8088/` - Caddy answers with the current report. A 200
   from a *different* service means the port is taken; change
   `NEWS_RADAR_HTTP_PORT` rather than guessing.
3. `curl http://localhost:8088/news.db` - **`404`**. The store shares the
   volume with the pages, and this is the Caddyfile rule that keeps it out of
   reach of anyone who can reach the port. `curl http://localhost:8088/days/`
   must answer `404` too.
4. `docker compose logs news-radar | head` - `news-radar <version> starting`.
   That version is the one the image was published as, so it is also how you
   read whether an update actually landed.
5. Wait one `schedule.interval_minutes` and check that Telegram and Discord each
   received exactly one message.

Updating a deployment, freezing or rolling back a version, and turning an
existing checkout into a deployment are all [[updating-homelab]].
