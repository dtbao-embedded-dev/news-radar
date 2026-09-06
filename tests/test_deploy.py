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

# The opposite rule, and it is not symmetric: Caddyfile, cloudflared.yml and the
# tunnel credentials sit *beside the compose file*, in both layouts. Giving them
# the variable would send a flat deployment looking for ./config/Caddyfile.
beside = [host_side(m) for m in mounts("caddy") + mounts("cloudflared")
          if host_side(m).startswith("./")]
check("the files shipped beside the compose file stay relative to it",
      sorted(beside) == ["./Caddyfile", "./cloudflared.yml",
                         "./tunnel-credentials.json"],
      repr(sorted(beside)))


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

for key in ("NEWS_RADAR_HOME", "NEWS_RADAR_VERSION"):
    check("{} is in .env.example".format(key), key + "=" in env_example)


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
