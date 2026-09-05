---
title: Script CLIs - setup.py and release.py
category: interface
purpose: The command-line contract of the two standalone scripts, including exit codes and what each flag guarantees.
status: active
updated: 2026-09-05
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

Bootstraps a homelab checkout and starts it: verifies the toolchain, creates the
real config and env files from their templates, validates the notification
secrets, then brings the stack up. A successful run leaves nothing for the
operator to type afterwards.

| Flag | Guarantee |
|------|-----------|
| *(none)* | Interactive. Creates missing files, prompts for missing secrets, never overwrites an existing file |
| `--dry-run` | **Writes nothing, prompts for nothing, starts nothing.** Prints the checks, the files it would create and the compose command it would run, then exits |
| `--force` | Overwrite files that already exist. Without it, an existing file is reported and left alone |
| `--non-interactive` | Never prompt; leave a missing secret blank and report it. For unattended provisioning |
| `--check` | Verify only: toolchain present, required files exist. Creates nothing and starts nothing |

Steps, in order:

1. Check Python is 3.11 or newer.
2. Check `docker` and `docker compose` are on `PATH`; report the versions.
3. Create `config/config.yaml` from `config/config.yaml.example` if absent.
4. Create `docker/.env` from `docker/.env.example` if absent.
5. For each notification channel enabled in the config, ensure its variables are
   present and non-empty in `docker/.env`; prompt unless `--non-interactive`.
6. `docker compose -f docker/docker-compose.yml up -d`, with docker's own output
   inherited rather than captured. While no `Dockerfile` is present in the
   checkout the crawl service cannot build, so only `caddy` is named; the
   narrowing lifts by itself once the file exists.
7. Print the URL the page is served on, taking `NEWS_RADAR_HTTP_PORT` from
   `docker/.env` and falling back to `8088`.

Steps 6 and 7 are skipped by `--dry-run` and by `--check`.

| Exit code | Meaning |
|-----------|---------|
| `0` | Everything needed is in place (or, under `--dry-run`, would be) |
| `1` | A prerequisite is missing, a required secret is still empty, or `docker compose up` failed |
| `2` | Bad usage - unknown flag, or a template file is missing from the checkout |

## scripts/release.py

```
python scripts/release.py <version> [--dry-run] [--yes] [--remote <name>]
```

`<version>` is the only positional argument. It accepts `0.1.0` or `v0.1.0` and
normalises both to `v0.1.0` for the tag and the commit subject. Anything that is
not three dot-separated numbers is rejected before git is touched.

It does **not** read the commit log. The changelog is hand-written into the
`Unreleased` section as the work happens; this script only renames that section
to the version being cut. See [[changelog]].

| Flag | Guarantee |
|------|-----------|
| *(none)* | Runs the full release, printing the whole git chain and asking once for confirmation **before executing any of it** |
| `--dry-run` | **Touches nothing.** Prints the `Unreleased` body it would promote and the exact git commands in execution order, then exits `0` |
| `--yes` | Skip the confirmation prompt. For CI or a scripted release |
| `--remote <name>` | Push target, default `origin` |

Preflight, all before any write:

1. `<version>` parses as `vMAJOR.MINOR.PATCH`.
2. The working tree is clean.
3. The current branch matches `release/*`.
4. Tag `v<version>` does not already exist locally or on the push remote -
   the one `--remote` names, not always `origin`.
5. Branches `developing` and `main` exist.
6. `CHANGELOG.md` has an `## Unreleased` section **and it is not empty** - see
   [[changelog]]. The two failures are distinguished: no section at all, versus a
   section nobody wrote into.

A failed preflight exits non-zero with nothing changed. Under `--dry-run` the
same checks run but only report: a dry run must be readable from a branch that
could not release yet. See [[release-flow]] for the full procedure and the branch
chain it drives.

| Exit code | Meaning |
|-----------|---------|
| `0` | Release completed, or `--dry-run` printed the plan |
| `1` | Preflight failed - wrong branch, dirty tree, tag exists, nothing under `Unreleased` - or the confirmation was declined |
| `2` | Bad usage - missing or malformed `<version>` |
| `3` | A git command failed mid-run; the message names the step and what to inspect |

## Shared conventions

- Both scripts run identically on Windows and Linux. No shell, no `sh -c`: every
  external call goes through `subprocess.run` with an argument list.
- Both print one line per step, prefixed `[ok]`, `[new]`, `[skip]`, `[warn]` or
  `[dry]`, so the output is scannable and greppable.
- Neither imports anything from `src/news_radar`, and neither needs PyYAML: the
  config template is copied verbatim, not parsed.
