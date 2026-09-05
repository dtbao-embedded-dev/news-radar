---
title: What Goes in the Changelog
category: rule
purpose: What is recorded in CHANGELOG.md and what is not, when the entry is written, and how release.py turns the Unreleased section into a version.
status: active
updated: 2026-09-05
source: CHANGELOG.md, scripts/release.py, tests/test_release.py
confidence: confirmed
keywords: changelog, CHANGELOG.md, Unreleased, technical change, release notes, promote_unreleased, unreleased_body, entry, scope
order: 4
---

# What Goes in the Changelog

> `CHANGELOG.md` records **technical changes only**, written by hand into the
> `Unreleased` section **in the same commit as the change itself**. It is not
> generated from commit subjects, and it is not a log of everything that
> happened in the repository.

## Why it is written by hand

Deriving the changelog from commit subjects was tried and dropped. The commit
log is a record of *work*; the changelog is a record of *what changed in the
software*. They are not the same set. At the point that decision was made, 16 of
28 commits were `docs` — a generated changelog would have been 57% bookkeeping,
and the reader would have had to find the three fixes inside it.

Writing the entry by hand also puts it where the knowledge is: at the moment of
the change, by the person making it, in words aimed at someone who has to decide
whether to upgrade.

## What is a technical change

A change to **what the software does, or how it is built and shipped**.

| Recorded | Not recorded |
|----------|--------------|
| `feat` — a new capability | `docs` — README, the memory bank, comments |
| `fix` — a defect a user or operator could hit | `chore` — housekeeping, dependency bumps with no behaviour change |
| `perf` — measurably faster or lighter | `style` — formatting only |
| `refactor` — the code changed shape | `ci` — workflow plumbing, unless it changes what ships |
| `build` — how it is packaged, imaged or run | `test` — tests added or reorganised |
| **breaking** — see below | Anything reverted before it was released |

The line is the reader: someone deciding whether to take a new version. A CI
workflow does not affect that decision; the compose stack it produces does.

**Breaking changes are never optional.** A change that invalidates an existing
`config.yaml`, `frequency_words.txt`, or output contract goes in under its own
`### Breaking Changes` heading, at the top of the section, even when the change
itself is small.

## Where and how

`CHANGELOG.md` opens with an `## Unreleased` section. Add the entry there, in
the same commit as the change:

```markdown
## Unreleased

### Features

- **setup**: bring the stack up directly instead of printing the command to run

### Fixes

- **release**: check the tag on the push remote rather than always `origin`
```

- Group under `### Breaking Changes`, `### Features`, `### Fixes`,
  `### Performance`, `### Refactoring`, `### Build` — in that order, omitting
  the empty ones.
- One entry per line, starting `- `. Lead with `**scope**: ` when the change is
  confined to one area; drop it when it is not.
- Write what changed and why it matters, in the present tense, from the
  reader's side. `check the tag on the push remote rather than always origin`
  beats `fix tag_exists`.
- One entry per change, not one per commit. Three commits fixing one defect are
  one line.

## What release.py does with it

`python scripts/release.py <version>` does not read the commit log. It:

1. **Refuses to release an empty section.** Preflight fails when `Unreleased` is
   missing or has no body — a release with nothing recorded is a mistake, not an
   empty release. `unreleased_body()` distinguishes the two: `None` for a missing
   section, `""` for an empty one.
2. **Promotes** `## Unreleased` to `## v<version> - <date>` and opens a fresh
   empty `## Unreleased` above it (`promote_unreleased()`).
3. Leaves everything below untouched, newest version first.

CI then publishes that version's section as the GitHub Release notes, cut by
`extract_changelog_section()` — the same function, so there is no second parser.
See [[release-flow]] for the rest of the release procedure.

## Rules

1. **Never write a `## v...` heading by hand.** `release.py` owns every version
   heading. Fixing wording inside an existing section is fine; adding a heading
   makes the file and the tags disagree.
2. **The entry ships with the change.** Not "before the release" — by then the
   detail that made the entry worth writing is gone.
3. **If it is not worth an entry, it is not a technical change.** That is the
   test, and it is allowed to come out negative: most commits in this repository
   never touch the changelog.
4. **Never delete a released section** to correct history. Cut the next patch and
   say what was wrong.
