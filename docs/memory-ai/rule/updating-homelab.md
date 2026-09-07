---
title: Updating and Migrating a Homelab Deployment
category: rule
purpose: How a running deployment takes a new release, how to freeze or roll one back, and the one-time procedure that turns an existing git checkout into a deployment.
status: active
updated: 2026-09-07
source: docker/docker-compose.yml, docker/.env.example, .github/workflows/image.yml, src/news_radar/__main__.py, src/news_radar/ops.py
confidence: confirmed
keywords: updating, upgrade, docker compose pull, watchtower, autoupdate profile, auto-update, NEWS_RADAR_VERSION, freeze, rollback, pin version, ghcr private, package visibility, --check, config drift, migrating, migration, git checkout, tunnel removal, ops.heartbeat_url, dead-man's switch
order: 3
---

# Updating and Migrating a Homelab Deployment

> A deployment takes a new release by pulling an image, never by checking out a
> tag - that is what keeps `config/`, `output/` and `backups/` out of reach of
> any command an update runs. Installing one in the first place is
> [[setup-homelab]].

## Updating

**By hand**, from the deployment directory:

```
docker compose pull
docker compose --profile autoupdate up -d
docker compose run --rm news-radar --check
```

**By itself.** The `autoupdate` profile runs a `watchtower` container that polls
GHCR every `WATCHTOWER_POLL_INTERVAL` seconds (86400 by default), pulls a newer
`:latest`, and recreates the crawl container. It touches only that one - it is
the only service carrying `com.centurylinklabs.watchtower.enable`, because caddy
is the one thing serving the report and should not upgrade itself unreviewed.

**Freezing a version is one change.** Set `NEWS_RADAR_VERSION=<version>` in
`.env` and `up -d`. Watchtower polls the tag the running container was created
from, so a pinned deployment stays put even with the profile on - a version tag
does not move. The same one change is how a rollback works. Turning the profile
off as well only matters if that exact version tag gets republished, which a
re-run of the publish workflow would do.

**Auto-update has no safety net yet, and this is the thing to weigh before
turning it on.** A release whose *cycles* fail is reported: `ops.Health` sends
one message on the second consecutive failure. A release that **will not start**
is not reported at all - the process exits before `ops.Health` is built, and
every restart is a fresh process, so the counter never reaches two. Measured: 9
restarts in 45 seconds, zero messages. The only thing that catches that shape is
the dead-man's switch, and `ops.heartbeat_url` ships empty. **Put a
healthchecks.io or Uptime Kuma push url in `config/config.yaml` before starting
with `--profile autoupdate`**, or accept that a bad release goes unnoticed until
someone opens the page.

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
| `docker-compose.yml`, `Caddyfile` | **not updated either** - they came from a release by hand. Re-fetch them when a release says to |

The last row is the one to remember: a pull updates the code, never the compose
file that runs it. A release that changes the stack's shape says so in
`CHANGELOG.md`.

## Migrating an existing checkout

For the homelab as it stands today: a detached checkout at `~/news-radar` with
`config/`, `output/` and `backups/` inside it. **No data moves in either phase.**

Cut and publish a version first - the image has to exist before anything can
pull it. `python scripts/release.py <version>` from a development checkout, then
watch the `Publish image` workflow go green, then confirm from the homelab
that the image is pullable - it came out public and needed no login the first
time, but `denied` here means the package's visibility needs one click, see
[[setup-homelab]]:

```
docker pull ghcr.io/dtbao-embedded-dev/news-radar:<version>
```

Nothing below works until that command does.

**Phase 1 - stop being a checkout.** This is the whole of the fix; everything
after it is tidying.

```
cd ~/news-radar
docker compose -f docker/docker-compose.yml --profile tunnel down

rm -rf .git .github
BASE=https://raw.githubusercontent.com/dtbao-embedded-dev/news-radar/v<version>
curl -fsSL "$BASE/docker/docker-compose.yml" -o docker/docker-compose.yml

# The tunnel is gone from the stack. Nothing reads these any more, and the
# credentials file is the one piece of it that was a secret.
rm -f docker/cloudflared.yml docker/tunnel-credentials.json

docker compose -f docker/docker-compose.yml pull
docker compose -f docker/docker-compose.yml --profile autoupdate up -d
docker compose -f docker/docker-compose.yml run --rm news-radar --check
```

**The public hostname stops answering, and that is the intended outcome.** This
release removes the tunnel: the report is served on
`http://<host>:NEWS_RADAR_HTTP_PORT` and nowhere else. Two loose ends the
commands above do not tidy for you:

- **`ops.site_url` in `config/config.yaml` may still be the public URL**, and
  this is the urgent one. Point it at `http://caddy:8080/`, which resolves over
  the compose network, then restart the crawl so it re-reads the config. Left as
  the public name it fetches a hostname nothing serves, fails every cycle, and
  two failures in a row is a genuine alert about a non-problem. Do it **before**
  the next cycle, not after;
- **the tunnel and its DNS record are account operations.**
  `cloudflared tunnel delete <name>` removes the tunnel and needs
  `~/.cloudflared/cert.pem`, not the credentials file. The CNAME is the part no
  CLI can do: `cloudflared tunnel route` only *creates* records, so deleting it
  is a dashboard or API job. Until it goes, the hostname answers **530** - it
  still resolves, and points at a tunnel that no longer exists.

`NEWS_RADAR_HOME` stays **unset** here: the compose file sits in `docker/`, the
default `..` is `~/news-radar`, and that is already where `config/`, `output/`
and `backups/` are. Nothing is moved and no path changes.

**Phase 2 - flatten it, optional.** Only worth doing to stop the leftover `src/`
and `scripts/` from looking like something anyone should run.

```
cd ~/news-radar
docker compose -f docker/docker-compose.yml --profile autoupdate down
mv docker/.env docker/Caddyfile .
mv docker/docker-compose.yml .
printf '\nNEWS_RADAR_HOME=.\n' >> .env
rm -rf docker src scripts tests docs Dockerfile requirements.txt VERSION \
       README.md CHANGELOG.md CLAUDE.md LICENSE .gitignore
docker compose --profile autoupdate up -d
```

`ls` before the `rm -rf` and confirm `config`, `output` and `backups` are not in
that list. They are the three directories this whole change exists to protect.

Cutting the version in the first place is [[release-flow]]; what the stack looks
like once it is running is [[deployment-homelab]]; installing one from nothing is
[[setup-homelab]].
