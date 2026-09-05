#!/usr/bin/env python3
"""Bootstrap a news-radar checkout on a homelab machine.

One script, identical behaviour on Windows and Linux: check the toolchain,
create the real config and env files from their committed templates, make sure
every notification secret the stack needs is actually filled in, and bring the
stack up. Nothing is left for the reader to run afterwards.

Standard library only, on purpose - this runs before anything is installed.
Nothing here imports src/news_radar, and nothing here parses YAML: the config
template is copied verbatim.

    python scripts/setup.py [--dry-run] [--force] [--non-interactive] [--check]

Exit codes: 0 all good, 1 prerequisite/secret missing or the stack failed to
start, 2 bad usage.
See docs/memory-ai/interface/cli-scripts.md for the full contract.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MIN_PYTHON = (3, 11)

# (template, destination) - both relative to the repo root.
TEMPLATES = [
    (Path("config/config.yaml.example"), Path("config/config.yaml")),
    (Path("docker/.env.example"), Path("docker/.env")),
]

ENV_FILE = Path("docker/.env")
COMPOSE_FILE = Path("docker/docker-compose.yml")

# Gitignored, placed by hand from the Cloudflare Tunnel's credentials. Its
# presence is what turns the `tunnel` compose profile on - see compose_argv().
TUNNEL_CREDENTIALS = Path("docker/tunnel-credentials.json")

# Mirrors the fallback in docker-compose.yml; 8080 is commonly taken already.
DEFAULT_HTTP_PORT = "8088"

# Channel -> the variables it cannot work without. Kept as a constant rather
# than read from config.yaml: parsing YAML would mean a dependency, and this
# script has to run on a bare Python install. Both channels ship enabled in
# config.yaml.example; disable one there and leave its variables blank here.
REQUIRED_SECRETS = {
    "telegram": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
    "discord": ["DISCORD_WEBHOOK_URL"],
}

HINTS = {
    "TELEGRAM_BOT_TOKEN": "from @BotFather",
    "TELEGRAM_CHAT_ID": "from https://api.telegram.org/bot<TOKEN>/getUpdates",
    "DISCORD_WEBHOOK_URL": "channel settings -> Integrations -> Webhooks",
}


def say(tag, msg):
    """One scannable line per step: [ok] [new] [skip] [warn] [dry] [fail]."""
    print("[{}]{}{}".format(tag, " " * max(1, 6 - len(tag)), msg))


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------


def check_python():
    v = sys.version_info
    if (v.major, v.minor) < MIN_PYTHON:
        say("fail", "python {}.{} is too old, need >= {}.{}".format(
            v.major, v.minor, MIN_PYTHON[0], MIN_PYTHON[1]))
        return False
    say("ok", "python {}.{}.{}".format(v.major, v.minor, v.micro))
    return True


def _first_line(cmd):
    """Run cmd, return its first stdout line, or None if it is unusable."""
    exe = shutil.which(cmd[0])
    if exe is None:
        return None
    try:
        proc = subprocess.run(
            [exe] + cmd[1:], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out.splitlines()[0] if out else ""


def check_docker():
    engine = _first_line(["docker", "--version"])
    if engine is None:
        say("fail", "docker not found on PATH - install Docker Engine or Docker Desktop")
        return False
    say("ok", engine)

    compose = _first_line(["docker", "compose", "version"])
    if compose is None:
        say("fail", "docker compose v2 not available - 'docker compose version' failed")
        return False
    say("ok", compose)
    return True


# --------------------------------------------------------------------------
# files
# --------------------------------------------------------------------------


def ensure_file(src, dst, dry_run, force):
    """Create dst from src. Returns False only on a real failure."""
    src_abs = ROOT / src
    dst_abs = ROOT / dst

    if not src_abs.is_file():
        say("fail", "template missing from the checkout: {}".format(src))
        return False

    if dst_abs.exists() and not force:
        say("skip", "{} exists, left alone (use --force to overwrite)".format(dst))
        return True

    verb = "overwrite" if dst_abs.exists() else "create"
    if dry_run:
        say("dry", "would {} {}  <- {}".format(verb, dst, src))
        return True

    dst_abs.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_abs, dst_abs)
    say("new", "{}  <- {}".format(dst, src))
    return True


# --------------------------------------------------------------------------
# secrets
# --------------------------------------------------------------------------


def read_env(path):
    """Parse KEY=VALUE lines. Comments and blanks ignored; no quoting rules."""
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def write_env_value(path, key, value):
    """Set key in an existing .env, preserving comments and line order."""
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(key + "="):
            lines[i] = "{}={}".format(key, value)
            break
    else:
        lines.append("{}={}".format(key, value))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_secrets(dry_run, interactive, verify=False):
    """True when every required secret is non-empty.

    `verify` is --check: a blank secret is a finding, not a plan. --dry-run
    describes a checkout that does not exist yet and only lists what it would
    ask for; --check inspects one that does, so it has to report the gap or it
    would call an install ready that cannot start.
    """
    env_abs = ROOT / ENV_FILE
    values = read_env(env_abs)
    missing = []

    for channel, keys in REQUIRED_SECRETS.items():
        for key in keys:
            if values.get(key):
                say("ok", "{} set ({})".format(key, channel))
                continue

            if dry_run and not verify:
                say("dry", "would ask for {} ({}, {})".format(
                    key, channel, HINTS.get(key, "")))
                continue

            if interactive and env_abs.is_file():
                prompt = "       {} ({}), blank to skip: ".format(key, HINTS.get(key, ""))
                try:
                    entered = input(prompt).strip()
                except EOFError:
                    entered = ""
                if entered:
                    write_env_value(env_abs, key, entered)
                    values[key] = entered
                    say("new", "{} written to {}".format(key, ENV_FILE))
                    continue

            say("warn", "{} is empty in {} - {} will not send".format(key, ENV_FILE, channel))
            missing.append(key)

    return not missing


# --------------------------------------------------------------------------
# stack
# --------------------------------------------------------------------------


def compose_argv(root=None):
    """The `up -d` argv for whatever can actually start in this checkout.

    Two narrowings, both read off the filesystem rather than asked about:

    - No `Dockerfile` means the crawl service cannot build and a full `up -d`
      would die on it, so bring up the web half alone.
    - The `cloudflared` service sits behind the `tunnel` compose profile and
      mounts a credentials file that is never committed. The profile goes on
      only when that file is there; a checkout without one starts exactly what
      it started before rather than a container crash-looping on the mount.

    `root` exists so the rules can be exercised against a throwaway tree - see
    tests/test_setup.py. It defaults to this checkout.
    """
    root = ROOT if root is None else root
    # as_posix(): the same printed command works when pasted into any shell,
    # including a Windows one, instead of growing backslashes there.
    argv = ["docker", "compose", "-f", COMPOSE_FILE.as_posix()]
    if (root / TUNNEL_CREDENTIALS).is_file():
        argv += ["--profile", "tunnel"]
    argv += ["up", "-d"]
    if not (root / "Dockerfile").is_file():
        argv.append("caddy")
    return argv


def start_stack():
    """Bring the stack up. Docker's own output is inherited, not captured."""
    argv = compose_argv()
    exe = shutil.which(argv[0])
    if exe is None:
        say("fail", "docker is no longer on PATH")
        return False

    if argv[-1] == "caddy":
        say("warn", "no Dockerfile in the checkout - starting caddy only")
    say("run", " ".join(argv))

    # docker writes to this same stdout unbuffered, but Python block-buffers it
    # whenever it is not a tty - a piped run or a CI log would otherwise show
    # docker's lines above the banner that explains them.
    sys.stdout.flush()
    sys.stderr.flush()

    try:
        proc = subprocess.run([exe] + argv[1:], cwd=str(ROOT), check=False)
    except OSError as exc:
        say("fail", "could not run docker compose: {}".format(exc))
        return False
    if proc.returncode != 0:
        say("fail", "docker compose exited {}".format(proc.returncode))
        return False

    port = read_env(ROOT / ENV_FILE).get("NEWS_RADAR_HTTP_PORT") or DEFAULT_HTTP_PORT
    say("ok", "stack is up - http://localhost:{}".format(port))
    return True


# --------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="setup.py",
        description="Bootstrap a news-radar checkout for the homelab.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="write nothing, prompt for nothing")
    parser.add_argument("--force", action="store_true",
                        help="overwrite files that already exist")
    parser.add_argument("--non-interactive", action="store_true",
                        help="never prompt; report a missing secret instead")
    parser.add_argument("--check", action="store_true",
                        help="verify only, create nothing")
    args = parser.parse_args(argv)

    if args.check and args.force:
        parser.error("--check and --force are mutually exclusive")

    # --check verifies without writing, so it shares the dry path.
    dry = args.dry_run or args.check

    print("news-radar setup  ({})".format(ROOT))

    ok = check_python()
    ok = check_docker() and ok

    for src, dst in TEMPLATES:
        ok = ensure_file(src, dst, dry, args.force) and ok

    interactive = not args.non_interactive and not dry
    secrets_ok = ensure_secrets(dry, interactive, verify=args.check)

    print()
    if args.dry_run:
        # A dry run reports what would happen; it never fails on state it was
        # explicitly told not to change.
        say("dry", "would run: {}".format(" ".join(compose_argv())))
        say("dry", "nothing was written")
        return 0 if ok else 1

    if not ok:
        say("fail", "prerequisites missing - fix the lines above and re-run")
        return 1
    if not secrets_ok:
        say("fail", "fill the empty values in {}, then re-run".format(ENV_FILE))
        return 1

    if args.check:
        say("ok", "checkout is ready - re-run without --check to start the stack")
        return 0

    return 0 if start_stack() else 1


if __name__ == "__main__":
    sys.exit(main())
