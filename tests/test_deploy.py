#!/usr/bin/env python3
"""Checks for the shipped deployment files - plain asserts, no test framework.

    python tests/test_deploy.py

Unlike test_setup.py, this one reads the repository's *real*
docker/docker-compose.yml on purpose: the claim being pinned is about the file
that ships, not about a function's logic. A deployment that mounts the wrong
directory is not a bug you find in a unit test.

Needs PyYAML, which is already a runtime dependency.
"""

from __future__ import annotations

import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "docker" / "docker-compose.yml"
ENV_EXAMPLE = ROOT / "docker" / ".env.example"
WORKFLOW = ROOT / ".github" / "workflows" / "image.yml"

# The one string that says where a deployment's own files live. Both layouts are
# driven by it: unset it is `..` (the repo root, which is what a dev checkout
# wants), and a flat deployment directory sets it to `.`.
HOME = "${NEWS_RADAR_HOME:-..}"

# Repeated in .github/workflows/image.yml. The check below pins that the two
# agree, because a compose file pointing at an image nothing publishes fails at
# `docker compose pull` on the machine furthest from anyone who could fix it.
IMAGE = "ghcr.io/dtbao-embedded-dev/news-radar"

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        return
    FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
services = compose.get("services", {})
env_example = ENV_EXAMPLE.read_text(encoding="utf-8")
workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
workflow_text = WORKFLOW.read_text(encoding="utf-8")


def mounts(service):
    """The `host:container[:mode]` strings of one service, host side first."""
    return [str(v) for v in services.get(service, {}).get("volumes", []) or []]


def host_side(mount):
    """The host half of a bind mount, `${VAR:-..}/x` and all.

    rsplit rather than split: the container side is an absolute path carrying
    colons of its own, while the host side is what comes before the *last* two.
    """
    parts = mount.split(":")
    if parts and parts[-1] in ("ro", "rw", "z", "Z"):
        parts = parts[:-1]
    return ":".join(parts[:-1]) if len(parts) > 1 else mount


# --------------------------------------------------------------------------
# every path a deployment owns is under NEWS_RADAR_HOME
# --------------------------------------------------------------------------

# config/, output/ and backups/ are the deployment's, not the repository's. The
# whole point of the variable is that production can point it somewhere no git
# command runs, so a mount that still says `..` is a file an update can reach.
for service, expected in (
    ("news-radar", ["/config", "/output", "/backups"]),
    # caddy serves the same output/ the crawl writes. If this one is left
    # behind, the crawl publishes to the deployment directory and the web server
    # serves an empty directory somewhere else - and the site 404s while every
    # log line says success.
    ("caddy", ["/output"]),
):
    hosts = [host_side(m) for m in mounts(service)]
    for suffix in expected:
        check("{} mounts {} from NEWS_RADAR_HOME".format(service, suffix),
              HOME + suffix in hosts, repr(hosts))

for service in ("news-radar", "caddy"):
    stale = [h for h in (host_side(m) for m in mounts(service))
             if h.startswith("..")]
    check("{} has no mount left pointing into the checkout".format(service),
          not stale, repr(stale))

# The opposite rule, and it is not symmetric: the Caddyfile sits *beside the
# compose file*, in both layouts. Giving it the variable would send a flat
# deployment looking for ./config/Caddyfile.
beside = [host_side(m) for m in mounts("caddy") if host_side(m).startswith("./")]
check("the files shipped beside the compose file stay relative to it",
      sorted(beside) == ["./Caddyfile"], repr(sorted(beside)))


# --------------------------------------------------------------------------
# the crawl service runs from a published image, and can still be built
# --------------------------------------------------------------------------

crawl = services.get("news-radar", {})
check("the crawl service names the GHCR image",
      crawl.get("image") == IMAGE + ":${NEWS_RADAR_VERSION:-latest}",
      repr(crawl.get("image")))
# Kept deliberately next to `image:`. A dev checkout builds what it is editing;
# production never builds because `pull` has already put the image there. The
# cost is one footgun - `up -d` before `pull` on production tries to build and
# dies on the absent Dockerfile - and it buys one compose file that cannot drift
# from a second one.
check("the crawl service can still be built locally",
      isinstance(crawl.get("build"), dict), repr(crawl.get("build")))


# --------------------------------------------------------------------------
# .env.example documents both new variables
# --------------------------------------------------------------------------

for key in ("NEWS_RADAR_HOME", "NEWS_RADAR_VERSION", "WATCHTOWER_POLL_INTERVAL"):
    check("{} is in .env.example".format(key), key + "=" in env_example)

# Removed with the cloudflared service, and pinned so it does not drift back in
# as a variable nothing reads.
check("no tunnel variable is left in .env.example",
      "NEWS_RADAR_TUNNEL_ID" not in env_example)


# --------------------------------------------------------------------------
# auto-update: opt-in, and pointed at exactly one container
# --------------------------------------------------------------------------

WATCH_LABEL = "com.centurylinklabs.watchtower.enable"


def labels(service):
    """A service's labels as a dict. Compose accepts a map or a `k=v` list."""
    raw = services.get(service, {}).get("labels", {}) or {}
    if isinstance(raw, list):
        return dict(str(item).split("=", 1) for item in raw if "=" in str(item))
    return {str(k): str(v) for k, v in raw.items()}


watchtower = services.get("watchtower", {})
check("there is a watchtower service", bool(watchtower))

# `containrrr/watchtower` is unmaintained: its Docker client speaks API 1.25 and
# Docker 29 refuses anything below 1.40, so it crash-loops on a modern daemon.
# Nothing in a YAML check can prove an image talks to a daemon - this only pins
# that the known-broken one does not come back.
check("watchtower is the maintained fork, not containrrr's",
      str(watchtower.get("image", "")).startswith("ghcr.io/nicholas-fedor/watchtower:"),
      repr(watchtower.get("image")))
# The tag is whatever follows the colon in the last path segment - counting
# colons in the whole reference is wrong, because a registry host may or may not
# carry a port.
wt_tag = str(watchtower.get("image", "")).rsplit("/", 1)[-1].partition(":")[2]
check("the watchtower image is pinned to an exact version",
      wt_tag not in ("", "latest"), repr(watchtower.get("image")))

# Opt-in, the same way the tunnel is. On a dev checkout watchtower would pull
# `:latest` from GHCR straight over the image the developer just built - the
# profile is what keeps `docker compose up -d` on this machine harmless.
check("watchtower is behind the autoupdate profile",
      watchtower.get("profiles") == ["autoupdate"],
      repr(watchtower.get("profiles")))

wt_env = watchtower.get("environment", {}) or {}
check("watchtower only touches labelled containers",
      str(wt_env.get("WATCHTOWER_LABEL_ENABLE")).lower() == "true",
      repr(wt_env.get("WATCHTOWER_LABEL_ENABLE")))

# caddy is `2-alpine` and cloudflared is pinned to an exact version; letting
# either self-upgrade would be an unreviewed change to the two things standing
# between the report and the public internet.
labelled = [name for name in services if labels(name).get(WATCH_LABEL) == "true"]
check("exactly the crawl container is labelled for auto-update",
      labelled == ["news-radar"], repr(labelled))

# The docker socket and nothing else. Note that `:ro` on a socket is not a
# sandbox - it stops the socket file being replaced, not the API calls that go
# through it - so what is pinned here is that watchtower sees no other path,
# and in particular nothing under NEWS_RADAR_HOME.
wt_mounts = [host_side(m) for m in mounts("watchtower")]
check("the docker socket is watchtower's only mount",
      wt_mounts == ["/var/run/docker.sock"], repr(mounts("watchtower")))


# --------------------------------------------------------------------------
# the workflow that publishes what the compose file points at
# --------------------------------------------------------------------------

# `"on"` is quoted in the workflow so YAML keeps it a string; bare `on:` parses
# as the boolean True, and every tool reading the file then disagrees about the
# key. release.yml carries the same comment and the same quoting.
check("the workflow triggers on a version tag, not on a boolean key",
      (workflow.get("on") or {}).get("push", {}).get("tags") == ["v*"],
      repr(list(workflow.keys())))
check('"on" is quoted in the source so it stays a string',
      '"on":' in workflow_text)

# Without packages: write the push fails at the end of a build nobody watched.
check("the workflow may write packages",
      workflow.get("permissions", {}).get("packages") == "write",
      repr(workflow.get("permissions")))

# The one string that has to agree across two files. A compose file pointing at
# an image nothing publishes fails at `docker compose pull`, on the machine
# furthest from anyone who could fix it.
check("the workflow publishes the image the compose file runs",
      IMAGE in workflow_text, IMAGE)

# The homelab is x86_64 (measured, not assumed), so a second architecture is
# build minutes bought for nobody. Read off the parsed step rather than counted
# in the file text - the first version of this check counted the word in a
# comment and failed on prose.
steps = workflow.get("jobs", {}).get("image", {}).get("steps", [])
build = [s for s in steps if str(s.get("uses", "")).startswith("docker/build-push-action")]
check("there is exactly one build-push step", len(build) == 1, repr(len(build)))
if build:
    with_ = build[0].get("with", {})
    check("the image is built for linux/amd64 only",
          with_.get("platforms") == "linux/amd64", repr(with_.get("platforms")))
    check("the build actually pushes", with_.get("push") is True,
          repr(with_.get("push")))
    check("both the version tag and latest are published",
          len([t for t in str(with_.get("tags", "")).splitlines() if t.strip()]) == 2,
          repr(with_.get("tags")))


# --------------------------------------------------------------------------
# nothing in this stack reaches the public internet
# --------------------------------------------------------------------------

# The Cloudflare Tunnel was removed deliberately: the report is served on the
# LAN and published nowhere. These pin the removal rather than the feature, so
# a connector cannot come back by accident and start answering from the
# internet without anybody deciding to.
check("there is no cloudflared service", "cloudflared" not in services,
      repr(sorted(services)))
check("no service declares a tunnel profile",
      not [n for n, s in services.items() if "tunnel" in (s.get("profiles") or [])],
      repr({n: s.get("profiles") for n, s in services.items()}))
check("the tunnel config file is gone",
      not (ROOT / "docker" / "cloudflared.yml").exists())

# Caddy is the only service with a published port, and it is the only way in.
published = {n: s.get("ports") for n, s in services.items() if s.get("ports")}
check("only caddy publishes a port", sorted(published) == ["caddy"],
      repr(published))


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
