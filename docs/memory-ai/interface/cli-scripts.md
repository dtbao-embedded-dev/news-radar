---
title: Script CLIs - setup.py and release.py
category: interface
purpose: The command-line contract of the two standalone scripts, including exit codes and what each flag guarantees.
status: active
updated: 2026-09-04
source: scripts/setup.py, scripts/release.py
confidence: confirmed
keywords: setup.py, release.py, --dry-run, --yes, --force, --non-interactive, --remote, exit codes, CLI
order: 2
---

# Script CLIs - setup.py and release.py

> Two standalone scripts, stdlib only, runnable on a machine where the package's
> dependencies are not installed. Both refuse to do anything surprising without
> being asked.

## scripts/setup.py

```
python scripts/setup.py [--dry-run] [--force] [--non-interactive] [--check]
```

Bootstraps a homelab checkout: verifies the toolchain, creates the real config
and env files from their templates, and validates the notification secrets.

| Flag | Guarantee |
|------|-----------|
| *(none)* | Interactive. Creates missing files, prompts for missing secrets, never overwrites an existing file |
| `--dry-run` | **Writes nothing and prompts for nothing.** Prints the checks and the files it would create, then exits |
| `--force` | Overwrite files that already exist. Without it, an existing file is reported and left alone |
| `--non-interactive` | Never prompt; leave a missing secret blank and report it. For unattended provisioning |
| `--check` | Verify only: toolchain present, required files exist, required secrets non-empty. Creates nothing |

Steps, in order:

1. Check Python is 3.11 or newer.
2. Check `docker` and `docker compose` are on `PATH`; report the versions.
3. Create `config/config.yaml` from `config/config.yaml.example` if absent.
4. Create `docker/.env` from `docker/.env.example` if absent.
5. For each notification channel enabled in the config, ensure its variables are
   present and non-empty in `docker/.env`; prompt unless `--non-interactive`.
6. Print the next command to run.

| Exit code | Meaning |
|-----------|---------|
| `0` | Everything needed is in place (or, under `--dry-run`, would be) |
| `1` | A prerequisite is missing, or a required secret is still empty |
| `2` | Bad usage - unknown flag, or a template file is missing from the checkout |

## scripts/release.py

```
python scripts/release.py <version> [--dry-run] [--yes] [--remote <name>]
```

`<version>` is the only positional argument. It accepts `0.1.0` or `v0.1.0` and
normalises both to `v0.1.0` for the tag and the commit subject. Anything that is
not three dot-separated numbers is rejected before git is touched.

| Flag | Guarantee |
|------|-----------|
| *(none)* | Runs the full release, printing the whole git chain and asking once for confirmation **before executing any of it** |
| `--dry-run` | **Touches nothing.** Prints the exact git commands in execution order and exits `0` |
| `--yes` | Skip the confirmation prompt. For CI or a scripted release |
| `--remote <name>` | Push target, default `origin` |

Preflight, all before any write:

1. `<version>` parses as `vMAJOR.MINOR.PATCH`.
2. The working tree is clean.
3. The current branch matches `release/*`.
4. Tag `v<version>` does not already exist locally or on the remote.
5. Branches `developing` and `main` exist.

A failed preflight exits non-zero with nothing changed. Under `--dry-run` the
same checks run but only report: a dry run must be readable from a branch that
could not release yet. See [[release-flow]] for the full procedure and the branch
chain it drives.

| Exit code | Meaning |
|-----------|---------|
| `0` | Release completed, or `--dry-run` printed the plan |
| `1` | Preflight failed - wrong branch, dirty tree, tag exists - or the confirmation was declined |
| `2` | Bad usage - missing or malformed `<version>` |
| `3` | A git command failed mid-run; the message names the step and what to inspect |

## Shared conventions

- Both scripts run identically on Windows and Linux. No shell, no `sh -c`: every
  external call goes through `subprocess.run` with an argument list.
- Both print one line per step, prefixed `[ok]`, `[new]`, `[skip]`, `[warn]` or
  `[dry]`, so the output is scannable and greppable.
- Neither imports anything from `src/news_radar`, and neither needs PyYAML: the
  config template is copied verbatim, not parsed.
