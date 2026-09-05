#!/usr/bin/env python3
"""Checks for scripts/setup.py - plain asserts, no test framework.

    python tests/test_setup.py

Covers only the pure logic: which `docker compose` argv the script would run
for a given checkout. Nothing here runs docker, and nothing here reads the
repository's own docker/ directory - every case builds a throwaway tree so the
answer does not depend on whether this machine happens to have a tunnel.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

import setup  # noqa: E402

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        return
    FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def checkout(tmp, dockerfile=True, credentials=False):
    """Build a fake checkout root and return it."""
    root = pathlib.Path(tmp)
    (root / "docker").mkdir(exist_ok=True)
    if dockerfile:
        (root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    if credentials:
        (root / "docker" / "tunnel-credentials.json").write_text("{}", encoding="utf-8")
    return root


# --------------------------------------------------------------------------
# the tunnel profile
# --------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    argv = setup.compose_argv(checkout(tmp, credentials=False))
    check("no credentials file means no tunnel profile",
          "--profile" not in argv, " ".join(argv))
    check("without the profile the stack is still started",
          argv[-2:] == ["up", "-d"], " ".join(argv))

with tempfile.TemporaryDirectory() as tmp:
    argv = setup.compose_argv(checkout(tmp, credentials=True))
    check("a credentials file turns the tunnel profile on",
          "--profile" in argv and "tunnel" in argv, " ".join(argv))
    check("the profile is declared before the up subcommand",
          argv.index("--profile") < argv.index("up"), " ".join(argv))

# --------------------------------------------------------------------------
# the Dockerfile narrowing, and that the two rules do not collide
# --------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    argv = setup.compose_argv(checkout(tmp, dockerfile=False))
    check("no Dockerfile still narrows to caddy", argv[-1] == "caddy", " ".join(argv))

with tempfile.TemporaryDirectory() as tmp:
    argv = setup.compose_argv(checkout(tmp, dockerfile=False, credentials=True))
    check("the caddy sentinel start_stack() reads survives the profile flag",
          argv[-1] == "caddy", " ".join(argv))
    check("both narrowings can apply at once",
          "--profile" in argv and argv[-1] == "caddy", " ".join(argv))

# --------------------------------------------------------------------------
# the default argument is the real repository root
# --------------------------------------------------------------------------

check("compose_argv defaults to the checkout it lives in",
      setup.compose_argv()[:4]
      == ["docker", "compose", "-f", setup.COMPOSE_FILE.as_posix()],
      " ".join(setup.compose_argv()))


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
