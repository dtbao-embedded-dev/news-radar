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
# config drift: keys the template gained that the local config never got
# --------------------------------------------------------------------------

# The shape that matters, in miniature: two levels, three levels under
# `notification`, and a list whose items carry keys of their own.
EXAMPLE = """\
app:
  timezone: Asia/Ho_Chi_Minh
report:
  mode: daily            # incremental | current | daily
  max_per_group: 0
notification:
  enabled: true
  channels:
    telegram:
      enabled: true
feeds:
  - id: hn
    url: https://example.invalid/hn
"""


def config_pair(tmp, local):
    """A checkout carrying the template above and `local` beside it."""
    root = pathlib.Path(tmp)
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "config.yaml.example").write_text(EXAMPLE, encoding="utf-8")
    if local is not None:
        (root / "config" / "config.yaml").write_text(local, encoding="utf-8")
    return root


with tempfile.TemporaryDirectory() as tmp:
    root = config_pair(tmp, EXAMPLE)
    check("an up-to-date config drifts by nothing",
          setup.missing_config_keys(root) == [],
          repr(setup.missing_config_keys(root)))

with tempfile.TemporaryDirectory() as tmp:
    # Exactly the shape that went unnoticed for a release: the template gained
    # a value for a key the deployment's own file never mentions.
    root = config_pair(tmp, EXAMPLE.replace(
        "  mode: daily            # incremental | current | daily\n", ""))
    check("a key only the template has is named",
          setup.missing_config_keys(root) == ["report.mode"],
          repr(setup.missing_config_keys(root)))

with tempfile.TemporaryDirectory() as tmp:
    root = config_pair(tmp, EXAMPLE.replace("      enabled: true\n", "", 1))
    check("a key three levels down is named in full",
          setup.missing_config_keys(root)
          == ["notification.channels.telegram.enabled"],
          repr(setup.missing_config_keys(root)))

with tempfile.TemporaryDirectory() as tmp:
    root = config_pair(tmp, EXAMPLE)
    # A list item is not a config key. `feeds[].id` differs per deployment by
    # design, and reporting it would make the check noise on every upgrade.
    check("keys inside a list item are not compared",
          not any("feeds." in k for k in setup.template_keys(
              root / "config" / "config.yaml.example")),
          repr(setup.template_keys(root / "config" / "config.yaml.example")))
    check("the top-level list itself is still a key",
          "feeds" in setup.template_keys(
              root / "config" / "config.yaml.example"))

with tempfile.TemporaryDirectory() as tmp:
    # No local config at all is `ensure_file()`'s business, not this check's -
    # it has just created one from the template, so nothing has drifted.
    root = config_pair(tmp, None)
    check("a checkout with no local config reports no drift",
          setup.missing_config_keys(root) == [],
          repr(setup.missing_config_keys(root)))


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
