---
title: Release Flow
category: rule
purpose: How a version is cut - the branch model, running release.py, what CI does with the tag, and what to do when it fails midway.
status: active
updated: 2026-09-05
source: scripts/release.py, .github/workflows/release.yml, .github/workflows/test.yml, CHANGELOG.md
confidence: confirmed
keywords: release, release.py, Unreleased, test.yml, CI checks, semver, tag, CHANGELOG.md, VERSION, developing, main, release branch, chore(release), GitHub Release
order: 1
---

# Release Flow

> One command cuts a release: `python scripts/release.py <version>`. Everything
> else - the changelog, the merges, the tag, the push, the GitHub Release - falls
> out of it. Nothing in this flow is done by hand.

## Branch model

| Branch | Role |
|--------|------|
| `main` | Released and stable. Only ever reached through `developing` |
| `developing` | Integration. Everything lands here before it reaches `main` |
| `release/<minor>` | Where a version line is prepared, e.g. `release/v0.1`. Day-to-day work happens here |

`main` and `developing` are listed in `protected_branches` in
`.claude/gitconfig.yml`, so ordinary commit tooling never pushes them.
`release.py` is the **deliberate** exception: pushing those two branches is the
whole point of a release, and it asks for confirmation before doing it.

## Versioning

Semantic versioning, `MAJOR.MINOR.PATCH`.

- `MAJOR` - a change that breaks an existing config, keyword file, or output contract.
- `MINOR` - a new capability that older configs still work with.
- `PATCH` - a fix with no new capability.

The tag is `v<version>`; `VERSION` holds the bare number without the `v`.

## Cutting a release

```
python scripts/release.py 0.1.0
```

`<version>` is the only required argument and takes either form (`0.1.0` or
`v0.1.0`). Useful flags: `--dry-run` to see the whole plan without touching
anything, `--yes` to skip the prompt, `--remote <name>` for a push target other
than `origin`.

**Always run `--dry-run` first.** It prints the changelog section that will be
written and the exact git commands in order, and it changes nothing.

What the real run does, in order:

1. **Preflight** - the version parses, the working tree is clean, the current
   branch is `release/*`, both `developing` and `main` exist, and the tag is not
   already taken locally or on the remote. A failure here changes nothing.
2. **Changelog** - renames the `## Unreleased` section of `CHANGELOG.md` to
   `## v0.1.0 - <date>` and opens a fresh empty one above it. It reads no commit
   subjects: the entries were written by hand as the work happened. An empty or
   missing `Unreleased` section fails the preflight - see [[changelog]].
3. **VERSION** - written to the bare number.
4. **Commit** - `CHANGELOG.md` and `VERSION` only, as
   `chore(release): v0.1.0`, on the current `release/*` branch.
5. **Merge chain** - `release/*` into `developing`, then `developing` into
   `main`, both `--no-ff` so the release is visible as a merge commit.
6. **Tag** - an annotated tag `v0.1.0` created while on `main`.
7. **Back and push** - returns to the `release/*` branch, then pushes the three
   branches and the tag.

CI takes over from the tag: `.github/workflows/release.yml` triggers on a pushed
`v*` tag, cuts that version's section out of `CHANGELOG.md` (using
`release.py`'s own extractor, so there is no second parser) and publishes it as
the GitHub Release notes. A version with no changelog section still publishes,
falling back to GitHub-generated notes and logging a warning.

The other half of CI runs before that: `.github/workflows/test.yml` runs every
`tests/test_*.py` on Python 3.12 on each push and pull request, with no install
step because the checks are standard library only. It is what keeps a broken
`release.py` from reaching a tag - the release workflow imports that same file.

## Rules

1. **Never write a version heading in `CHANGELOG.md` by hand.** `release.py`
   owns every `## v...` line. Writing into `## Unreleased` is the whole point;
   adding a version heading makes the file and the tags disagree.
2. **Never create the tag by hand**, and never push `main` or `developing`
   outside a release.
3. **Record the change in `Unreleased` as you make it**, in the same commit.
   The preflight refuses to cut a release with nothing recorded, so this is not a
   step you can leave until release day. What belongs there - technical changes
   only - is [[changelog]].
4. **Re-releasing the same version is not supported.** The preflight refuses a
   tag that exists. Cut the next patch instead of deleting a published tag.

## When it fails midway

Nothing is written until the preflight passes and the prompt is answered, so a
failure before that leaves the repository untouched.

After that point, `release.py` stops at the first failing git command, prints the
command and git's own message, and exits `3` without trying to unwind. That is
deliberate: a half-finished merge is something a human should look at, not
something a script should guess about.

Recovery is ordinary git. Find out which step failed from the output, then:

- **A merge conflict** - resolve it, commit the merge, and finish the remaining
  steps by hand from the list `--dry-run` prints.
- **The push was rejected** - fetch, reconcile, and re-push. The commits and the
  tag already exist locally.
- **Nothing usable happened yet** - `git switch` back to the release branch and
  reset the release commit; then re-run.
