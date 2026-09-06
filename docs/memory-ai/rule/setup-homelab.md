---
title: Setting Up on the Homelab
category: rule
purpose: The procedure from a fresh clone to news.dtbao.org serving, identical on Windows and Linux.
status: active
updated: 2026-09-06
source: scripts/setup.py, docker/docker-compose.yml, docker/Caddyfile, docker/cloudflared.yml
confidence: confirmed
keywords: upgrade, updating, detached tag, --build, git checkout, config drift, setup, setup.py, docker compose, homelab, cloudflare tunnel, cloudflared, tunnel profile, tunnel-credentials.json, news.dtbao.org, .env, config.yaml, NEWS_RADAR_HTTP_PORT, 8088
order: 2
---

# Setting Up on the Homelab

> Two steps: clone, then `python scripts/setup.py` - the script starts the stack
> itself. The same two on Windows and on Linux; that is why setup is a Python
> script and not a pair of shell scripts.

## Prerequisites

| Needs | Why |
|-------|-----|
| Python 3.11+ | Runs `setup.py` and `release.py`; `setup.py` checks the version and refuses an older one |
| Docker Engine + Compose v2 | Runs the stack. `setup.py` reports both versions before doing anything else |
| A free host port | The default published port is `8088`, overridable with `NEWS_RADAR_HTTP_PORT`. `8080` is deliberately not the default even though it is free - see [[deployment-homelab]] |

Nothing else. There are no API keys for fetching news; every secret is a
notification secret.

## Procedure

```
git clone git@github.com:dtbao-embedded-dev/news-radar.git
cd news-radar
python scripts/setup.py
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

**Step 3 happens inside step 2.** Once the checks pass and the secrets are
filled, `setup.py` runs `docker compose -f docker/docker-compose.yml up -d`
itself and prints the URL the page is served on. There is no separate command to
type. Two things it decides for itself by looking at the checkout: it names
`caddy` alone when there is no `Dockerfile` to build the crawl service from, and
it adds `--profile tunnel` when `docker/tunnel-credentials.json` is there. A
compose failure is reported and exits non-zero - the script never claims a stack
it could not start.

| Flag | Use it when |
|------|-------------|
| `--dry-run` | You want to see what it would do. Writes nothing, asks nothing |
| `--check` | Verifying an existing install - the same checks plus the secrets, a missing destination file, and any key the template has that your `config.yaml` does not. Creates nothing, non-zero on a gap. This is the upgrade's check - see `## Updating` |
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
host port (`8088` by default) is for local debugging only - the tunnel never
touches it.

The connector runs as the `cloudflared` service in this same compose project,
behind the `tunnel` profile. Two steps, once per machine:

1. **Have a tunnel.** `cloudflared tunnel create news` if there is none, then
   `cloudflared tunnel route dns news news.dtbao.org` to point the hostname at
   it. Both write to the Cloudflare account, not to this repo.
2. **Give the container its credentials.** Copy the tunnel's credentials JSON
   (`~/.cloudflared/<tunnel-id>.json`, written by `tunnel create`) to
   `docker/tunnel-credentials.json`. It is gitignored; the tunnel id in
   `docker/cloudflared.yml` is not a secret and stays committed. A different
   tunnel means editing that id.

After that `python scripts/setup.py` starts the tunnel too - it adds
`--profile tunnel` on its own once it sees the credentials file. By hand:

```
docker compose -f docker/docker-compose.yml --profile tunnel up -d
```

**Do not add `news.dtbao.org` to a connector running on the host instead.** A
host connector cannot resolve `caddy`, so it would have to be pointed at the
published debug port; and this homelab's host connector (`win-dev`) carries
`ssh.dtbao.org` and `remote.dtbao.org`, so restarting it for a news route drops
the operator's own remote access. See [[deployment-homelab]].

## Verifying it works

1. `docker compose -f docker/docker-compose.yml --profile tunnel ps` - all
   three services `running`. Drop `--profile tunnel` and `cloudflared`
   disappears from the listing; that is the profile working, not a fault.
2. `curl http://localhost:8088/` - Caddy answers with the current report.
   A 200 from a *different* service means the port is taken; change
   `NEWS_RADAR_HTTP_PORT` rather than guessing.
3. `curl https://news.dtbao.org/` - `200`, and the same report. This already
   leaves the LAN: the request goes out to the Cloudflare edge and comes back
   in through the tunnel. `curl https://news.dtbao.org/news.db` must answer
   `404`.
4. Cloudflare error `1033` there means the hostname is routed to a tunnel with
   no connector - read `docker compose logs cloudflared`, which prints
   `Registered tunnel connection` once per edge connection when it is healthy.
5. Wait one `schedule.interval_minutes` and check that Telegram and Discord each
   received exactly one message.

## Updating

Production runs a **detached checkout of a release tag**, not a tracking branch,
so `git pull` has nothing to pull onto. Four commands, from the checkout root:

```
git fetch --tags origin
git checkout v<version>
python scripts/setup.py --check
docker compose -f docker/docker-compose.yml --profile tunnel up -d --build
```

**`--build` is not optional.** `Dockerfile` copies `VERSION` and `src/` **into
the image**, so `up -d` without it recreates the container from the image it
already had and the new code never runs. The giveaway is the log line at
startup: `news-radar <version> starting`.

**`--check` is the step that reads the upgrade.** It exits `1`, naming the file
or the key, when either half of the config has fallen behind the release:

- a file `setup.py` is meant to create is **missing** - which is what a checkout
  does to `config/frequency_words.txt` the first time you upgrade past v0.2.2,
  because that file stopped being tracked and `git checkout` deletes a path the
  new commit does not carry;
- a **key** `config.yaml.example` has that the local `config.yaml` does not. The
  key is not fatal to the run - the code default fills it - but the default is a
  decision nobody made. `report.mode` sat at `incremental` through a release
  that had moved to `daily` exactly this way.

Fix either by running `python scripts/setup.py` with no flags: it creates what
is missing from the templates, never overwrites what exists, and brings the
stack up. A key it names has to be copied across by hand - a template is not
allowed to overwrite your config.

### What a checkout changes, and what it cannot

| Thing | On `git checkout v<version>` |
|-------|------------------------------|
| `src/`, `VERSION` | into the image, **only with `--build`** |
| `config/*.example`, `docker/.env.example` | updated on disk; nothing reads them at runtime |
| `config/config.yaml`, `config/frequency_words.txt`, `docker/.env` | **never touched** - all three are gitignored and yours |
| `output/news.db`, `output/days/`, `backups/` | untouched; they are bind mounts, not image content |

There is no config migration and there is not going to be one: the local files
are yours, and the release can only tell you what it added. That is what
`--check` is for.

The crawl container reads its config at startup, so any config change needs the
`up -d` above - see [[deployment-homelab]]. Cutting the version in the first
place is [[release-flow]].
