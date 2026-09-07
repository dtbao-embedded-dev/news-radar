---
title: Setting Up on the Homelab
category: rule
purpose: The procedure from nothing to a serving deployment running the published image, and to a development checkout.
status: active
updated: 2026-09-07
source: docker/docker-compose.yml, docker/.env.example, docker/Caddyfile, docker/cloudflared.yml, .github/workflows/image.yml, scripts/setup.py, src/news_radar/__main__.py
confidence: confirmed
keywords: deployment directory, NEWS_RADAR_HOME, NEWS_RADAR_VERSION, NEWS_RADAR_TUNNEL_ID, ghcr, image, docker compose pull, watchtower, autoupdate profile, auto-update, migrating, upgrade, updating, --check, config drift, setup, setup.py, homelab, cloudflare tunnel, cloudflared, tunnel profile, tunnel-credentials.json, news.dtbao.org, .env, config.yaml, NEWS_RADAR_HTTP_PORT, 8088
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
  cloudflared.yml            from the release
  .env                       yours - secrets, NEWS_RADAR_HOME=., tunnel id
  tunnel-credentials.json    yours
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
curl -fsSLO "$BASE/docker/cloudflared.yml"
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
docker compose --profile tunnel --profile autoupdate up -d
docker compose run --rm news-radar --check
```

**The GHCR package is private until somebody makes it public.** A package
published by a workflow inherits the repository's *access permissions* but
**not** its visibility, so a new one is private even from a public repo and the
`pull` above answers `denied`. Fix it once, on the package's page under the
repository's **Packages** - Package settings - Change visibility - Public. The
alternative is `docker login ghcr.io` on the homelab with a read:packages token,
which is a credential on the deployment for no benefit.

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

## Exposing news.dtbao.org

Caddy serves the deployment's `output/` inside the docker network on port
`8080`. The published host port (`8088` by default) is for local debugging only -
the tunnel never touches it.

The connector runs as the `cloudflared` service in this same compose project,
behind the `tunnel` profile. Two steps, once per machine:

1. **Have a tunnel.** `cloudflared tunnel create news` if there is none, then
   `cloudflared tunnel route dns news news.dtbao.org` to point the hostname at
   it. Both write to the Cloudflare account, not to this repo.
2. **Give the container its credentials.** Copy the tunnel's credentials JSON
   (`~/.cloudflared/<tunnel-id>.json`, written by `tunnel create`) to
   `tunnel-credentials.json` beside the compose file. It is never committed.
3. **Put the tunnel id in `.env`** as `NEWS_RADAR_TUNNEL_ID`
   (`cloudflared tunnel list` prints it; the credentials file carries the same
   one). It is not a secret, but it names one deployment, so it does not live in
   a committed file - and `cloudflared` will not read it from an environment
   variable inside its own config, which is why it is the argument to `run` in
   the compose command instead. Miss this and the connector starts with no
   tunnel to run: the site answers Cloudflare `1033` while everything else looks
   healthy.

   `docker/cloudflared.yml` names neither the tunnel nor the hostname. Its
   ingress is a single catch-all to `caddy:8080`, and only a hostname routed to
   this tunnel in Cloudflare DNS ever arrives.

**Do not add `news.dtbao.org` to a connector running on the host instead.** A
host connector cannot resolve `caddy`, so it would have to be pointed at the
published debug port; and this homelab's host connector (`win-dev`) carries
`ssh.dtbao.org` and `remote.dtbao.org`, so restarting it for a news route drops
the operator's own remote access. See [[deployment-homelab]].

## Verifying it works

1. `docker compose ps` - `news-radar` and `caddy` running, plus `cloudflared`
   and `watchtower` when their profiles are on. A service missing from the
   listing without its profile is the profile working, not a fault.
2. `curl http://localhost:8088/` - Caddy answers with the current report. A 200
   from a *different* service means the port is taken; change
   `NEWS_RADAR_HTTP_PORT` rather than guessing.
3. `curl https://news.dtbao.org/` - `200`, and the same report. This already
   leaves the LAN: out to the Cloudflare edge and back in through the tunnel.
   `curl https://news.dtbao.org/news.db` must answer `404`.
4. Cloudflare error `1033` there means the hostname is routed to a tunnel with
   no connector - read `docker compose logs cloudflared`, which prints
   `Registered tunnel connection` once per edge connection when it is healthy.
5. `docker compose logs news-radar | head` - `news-radar <version> starting`.
   That version is the one the image was published as, so it is also how you
   read whether an update actually landed.
6. Wait one `schedule.interval_minutes` and check that Telegram and Discord each
   received exactly one message.

Updating a deployment, freezing or rolling back a version, and turning an
existing checkout into a deployment are all [[updating-homelab]].
