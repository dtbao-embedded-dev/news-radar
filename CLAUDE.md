## Reference Repo

When a specific problem here is hard - a feed returning junk, dedup collapsing
the wrong stories, a message failing to format - **TrendRadar is the repo to go
read**: `docs/memory-ai/rule/reference-trendradar.md` says where to look by
problem, and what may never be copied back. It is GPL-3.0 and news-radar is a
clean-room reimplementation: carry the approach, never the code.

## Project Memory (docs/memory-ai/)

This project keeps a **memory bank** in `docs/memory-ai/` — a plain-text
description of what the code does, complete enough to understand the system or
rebuild an equivalent one, plus the project's conventions and current work state.
It contains prose, tables, and signatures, never pasted source code.

**Read the transient state first, every session:** `docs/memory-ai/progress.md`
(what works / what's left / known issues) and `docs/memory-ai/active-context.md`
(current focus / next steps). They tell you where the work is right now. Update
them at every checkpoint (feature shipped, milestone, direction change).

**To understand the code or rebuild from the bank:**

- If `docs/memory-ai/memory.md` exists, read **it** — it is the whole bank (the
  state layer, then every durable doc body) concatenated into one read, in
  reproduction order (architecture → data → interface → behavior → rule). That
  single file orients you fully; you do not need to open anything else.
- If it does not exist, read `docs/memory-ai/overview.md` — the map of every
  durable doc. Match a theme against the `Purpose` column and an exact name
  (symbol, config key, event) against `Keywords`; both point at the doc to open.

Read the five categories in this order to rebuild bottom-up, then follow project practice:

- `architecture/` — module/file layout, layering, dependencies, build + config + env.
- `data/`         — data model, schema, state, formats, invariants, constants.
- `interface/`    — public contracts: API, CLI, signatures, events, config keys.
- `behavior/`     — what each unit must do: logic, algorithms, flow, edge cases.
- `rule/`         — conventions, procedures, how-to ("how we do X here").

**Trust each durable statement by its confidence marker:** 🟢 `confirmed` (cited
from code), 🟡 `inferred` (deduced — verify against source before relying on it),
🔴 `gap` (unresolved — needs a human). Never rebuild a 🔴 gap without asking.

**When the bank has nothing on it — say so, do not fill the gap silently:** if
`overview.md` and the docs it points at do not cover the code in question, state
`not in the memory bank yet` before answering from the code itself, and keep the
two apart. Once confirmed, record it as a new doc (see below) so the next session
does not re-derive it.

**Keep the bank in sync — per category:**

| Category | Update when | How |
|----------|-------------|-----|
| `architecture/*` | Layout, a dependency, or the build changes | Update the affected doc; restamp `updated` |
| `data/*` | A struct/schema/format/invariant changes | Update the shape table; keep it scannable |
| `interface/*` | A signature, CLI, event, or config key changes | Update the contract; keep `keywords` current |
| `behavior/*` | The logic, flow, or an edge case changes | Update the steps; note new edge cases |
| `rule/*` | A convention or procedure changes | Update the rule; link the ADR that justifies it |

Each durable doc is a semantic `kebab-case.md` file with frontmatter (`title`,
`category`, `purpose`, `status`, `updated`, `source`, `confidence`, `keywords`,
optional `order`); the two state files carry only `title` + `updated`. One concept
per file, under ~300 lines, cite the `source:` path (with `:line` where it helps).
After any change, regenerate + check:
`python ~/.claude/skills/skill-memory-ai/scripts/memory_docs.py overview --root . && python ~/.claude/skills/skill-memory-ai/scripts/memory_docs.py digest --root . && python ~/.claude/skills/skill-memory-ai/scripts/memory_docs.py validate --strict --root .`
(`digest` rebuilds the single-read `memory.md`. Run `memory_docs.py coverage` separately
to see source files no doc covers yet.)
