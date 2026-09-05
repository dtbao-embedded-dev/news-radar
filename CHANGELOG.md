# Changelog

Everything notable in this project, newest first.

Entries are written **by hand, in the same commit as the change**, into the
`Unreleased` section below. `python scripts/release.py <version>` renames that
section to the version being cut and opens a fresh empty one; the CI release
workflow publishes a version's section as that release's notes.

Only technical changes are recorded here — a change to what the software does or
how it is built and shipped. Documentation, chores, CI plumbing, tests and
formatting are not. The full rule is `docs/memory-ai/rule/changelog.md`.

Never add a `## v...` heading by hand: `release.py` owns those, and a hand-written
one makes the file and the tags disagree.

## Unreleased

### Features

- **crawl**: the selection layer - `python -m news_radar --once` now prints a
  grouped, deduped, ranked shortlist instead of a raw item count. Every item is
  checked against the `[GLOBAL_FILTER]` exclusions first and dropped outright if
  one hits, then matched against each keyword group: plain terms compare on a
  folded title, so a keyword typed `dien tu` finds `Điện tử`, while a `/regex/`
  runs against the original title. `+` terms are all required and any `!` term
  blocks that group alone. Copies of one story collapse onto a single dedup key,
  keeping the earliest timestamp and the union of the sources that carried it,
  and each group is ordered by source weight, how many sources carried the story
  and how fresh it is - weights from `rank.*` - then cut to the group's `@n`,
  falling back to `report.max_per_group`. A story with no timestamp scores zero
  for freshness and one dated in the future scores no more than one published
  now. Nothing is stored, published or notified yet
- **crawl**: the fetch layer - `python -m news_radar --once` now pulls real
  items from the eight fixed feeds and from a search built out of every
  keyword group in `frequency_words.txt`, and prints a count per source.
  Adding a keyword group adds a hunting path with no code change. RSS, Atom
  and the HN Algolia JSON API are all read; a source that times out, is
  blocked or answers with something that is not a feed costs one warning line
  and never the run. Requests carry an identifying User-Agent and are spaced
  per hostname, so Reddit does not answer 403 and Google News does not
  throttle. Nothing is filtered, stored or notified yet
- **docker**: `Dockerfile` for the crawl service, base image pinned by digest,
  so `docker compose up -d` now builds and runs the whole stack
- **crawl**: `python -m news_radar` - the entrypoint and schedule loop, with
  `--once` for a single cycle. `SIGTERM` is honoured mid-interval and one
  failed cycle does not end the service
- **config**: load and validate `config.yaml` against every documented
  default; an enabled notification channel with no secret refuses to start,
  and a feed id that YAML turned into a boolean is rejected with the reason

### Fixes

- **setup**: `--check` reports a blank notification secret and exits non-zero
  instead of calling the checkout ready when it cannot start
- **setup**: flush stdout before handing over to docker, so its output lands
  under the line that announces it instead of above the banner in a piped log

## v0.1.0 - 2026-09-05

### Features

- **setup**: one homelab bootstrap script, same behaviour on Windows and Linux
- **setup**: bring the stack up directly instead of printing the command to run
- **release**: `release.py` with the branch chain, the tag and the push
- **release**: take the changelog from a hand-written `Unreleased` section
  instead of generating it from commit subjects; a release with nothing
  recorded is refused

### Fixes

- **release**: check the tag on the push remote rather than always `origin`
- **setup**: point at the compose command that can actually start
- **docker**: publish Caddy on a free host port; `8080` is taken by ntfy

### Build

- **config**: config templates and the homelab docker stack
