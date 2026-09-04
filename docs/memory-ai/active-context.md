---
title: Active Context
updated: 2026-09-04
---

# Active Context

> What is being worked on right now. Read first every session; rewrite when the focus shifts. Transient — not a durable fact.

## Current focus

Bootstrapping the repository. No application code exists yet.

## Recent changes

- Memory bank initialized (`docs/memory-ai/`) and wired into `CLAUDE.md`.
- Initial commit `chore: initialize repository` with a one-line `README.md`.
- Branches `main` and `developing` created and pushed to `origin`.

## Next steps

1. Decide what `news-radar` is and does, and what stack it is built on — nothing in the repo answers this.
2. Record that decision as `architecture/` docs (layout, build, config) plus an `adr/` entry.
3. Add a `.gitignore` matching the chosen stack.

## Active decisions

- Branch model: `main` is the released/stable branch, `developing` is the integration branch (inferred from the branch names requested, not yet written down as a rule).
