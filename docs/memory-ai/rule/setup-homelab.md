---
title: Setting Up on the Homelab
category: rule
purpose: The procedure from nothing to news.dtbao.org serving, for a deployment running the published image and for a development checkout.
status: active
updated: 2026-09-06
source: docker/docker-compose.yml, docker/.env.example, docker/Caddyfile, docker/cloudflared.yml, .github/workflows/image.yml, scripts/setup.py, src/news_radar/__main__.py
confidence: confirmed
keywords: deployment directory, NEWS_RADAR_HOME, NEWS_RADAR_VERSION, ghcr, image, docker compose pull, watchtower, autoupdate profile, auto-update, migrating, upgrade, updating, --check, config drift, setup, setup.py, homelab, cloudflare tunnel, cloudflared, tunnel profile, tunnel-credentials.json, news.dtbao.org, .env, config.yaml, NEWS_RADAR_HTTP_PORT, 8088
order: 2
---

# Setting Up on the Homelab

> A **deployment** runs the published image and keeps no source. A **checkout**
> is for developing. They share one `docker-compose.yml`, told apart by a single
> variable, so there is no second file to drift.

## Two ways to run it

| | Deployment (production) | Checkout (development) |
|---|---|---|
| What it holds | compose file, `.env`, and the deployment's own data | the whole repository |
| `NEWS_RADAR_HOME` | `.` - data beside the compose file | unset (`..`) - data at the repo root |
| Crawl image | pulled from GHCR | built from the local `Dockerfile` |
| Install | `docker compose pull && up -d` | `python scripts/setup.py` |
| Update | `docker compose pull && up -d`, or watchtower | `git pull`, rebuild |
| Git | **none** | yes |

**The absence of git on a deployment is the design, not a shortcut.** This
project has already lost a file to `git checkout <tag>` deleting a path the new
commit does not carry (`config/frequency_words.txt`, v0.2.2). A machine with no
checkout has no command that can do that to `config/`, `output/` or `backups/`.

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
  .env                       yours - secrets, and NEWS_RADAR_HOME=.
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

**`pull` first, always.** The compose file carries `image:` and `build:` both.
An `up -d` before the pull finds no image locally, tries to build, and dies on
the `Dockerfile` a deployment does not have. Pulling puts the image there and
nothing builds again.

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
default `..` is already the repo root.

| Flag | Use it when |
|------|-------------|
| `--dry-run` | You want to see what it would do. Writes nothing, asks nothing |
| `--check` | Verifying a checkout - the same checks plus the secrets, a missing destination file, and any key the template has that your `config.yaml` does not |
| `--force` | Regenerating a config from the template on purpose |
| `--non-interactive` | Unattended provisioning; a blank secret is reported, not prompted for |

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
   `tunnel-credentials.json` beside the compose file. It is never committed; the
   tunnel id in `cloudflared.yml` is not a secret and is. A different tunnel
   means editing that id.

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

## Updating

**By hand**, from the deployment directory:

```
docker compose pull
docker compose --profile tunnel --profile autoupdate up -d
docker compose run --rm news-radar --check
```

**By itself.** The `autoupdate` profile runs a `watchtower` container that polls
GHCR every `WATCHTOWER_POLL_INTERVAL` seconds (86400 by default), pulls a newer
`:latest`, and recreates the crawl container. It touches only that one - it is
the only service carrying `com.centurylinklabs.watchtower.enable`, because caddy
and cloudflared are version-pinned and should not upgrade themselves unreviewed.

**Freezing a version takes two changes, not one.** Set
`NEWS_RADAR_VERSION=<version>` in `.env` **and** start without
`--profile autoupdate`. Pinning alone loses to the next poll. The same pair is
how a rollback works.

**`--check` is what reads the upgrade.** `docker compose run --rm news-radar
--check` exits `1` naming every key that the release's `config.yaml.example` has
and your `config.yaml` does not. The key is not fatal to the run - the code
default fills it - but a default is a decision nobody made. `report.mode` sat at
`incremental` through a release that had moved to `daily` exactly this way.
Copy the named key across by hand: no release may overwrite your config, and
there is no config migration and is not going to be one.

### What an update changes, and what it cannot

| Thing | On `docker compose pull && up -d` |
|-------|-----------------------------------|
| `src/`, `VERSION` | replaced - they are inside the image |
| `config/config.yaml`, `config/frequency_words.txt`, `.env` | **never touched** - they are yours, and nothing in an update writes to them |
| `output/news.db`, `output/days/`, `backups/` | **never touched** - bind mounts, re-attached to the new container as they were |
| `docker-compose.yml`, `Caddyfile`, `cloudflared.yml` | **not updated either** - they came from a release by hand. Re-fetch them when a release says to |

The last row is the one to remember: a pull updates the code, never the compose
file that runs it. A release that changes the stack's shape says so in
`CHANGELOG.md`.

## Migrating an existing checkout

For the homelab as it stands today: a detached checkout at `~/news-radar` with
`config/`, `output/` and `backups/` inside it. **No data moves in either phase.**

Cut and publish a version first - the image has to exist before anything can
pull it. `python scripts/release.py <version>` from a development checkout, then
watch the `Publish image` workflow go green.

**Phase 1 - stop being a checkout.** This is the whole of the fix; everything
after it is tidying.

```
cd ~/news-radar
docker compose -f docker/docker-compose.yml --profile tunnel down
rm -rf .git .github
curl -fsSL https://raw.githubusercontent.com/dtbao-embedded-dev/news-radar/v<version>/docker/docker-compose.yml \
     -o docker/docker-compose.yml
docker compose -f docker/docker-compose.yml pull
docker compose -f docker/docker-compose.yml --profile tunnel --profile autoupdate up -d
docker compose -f docker/docker-compose.yml run --rm news-radar --check
```

`NEWS_RADAR_HOME` stays **unset** here: the compose file sits in `docker/`, the
default `..` is `~/news-radar`, and that is already where `config/`, `output/`
and `backups/` are. Nothing is moved and no path changes.

**Phase 2 - flatten it, optional.** Only worth doing to stop the leftover `src/`
and `scripts/` from looking like something anyone should run.

```
cd ~/news-radar
docker compose -f docker/docker-compose.yml --profile tunnel --profile autoupdate down
mv docker/.env docker/Caddyfile docker/cloudflared.yml docker/tunnel-credentials.json .
mv docker/docker-compose.yml .
printf '\nNEWS_RADAR_HOME=.\n' >> .env
rm -rf docker src scripts tests docs Dockerfile requirements.txt VERSION \
       README.md CHANGELOG.md CLAUDE.md LICENSE .gitignore
docker compose --profile tunnel --profile autoupdate up -d
```

`ls` before the `rm -rf` and confirm `config`, `output` and `backups` are not in
that list. They are the three directories this whole change exists to protect.

Cutting the version in the first place is [[release-flow]]; what the stack looks
like once it is running is [[deployment-homelab]].
