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

- **keywords**: the shipped `frequency_words.txt` now hunts AI. Two groups
  replace three: **AI** for the news and **AI Repos** for open-source projects,
  while `Embedded Linux`, `Rust on MCU` and `Security` are gone - six groups
  instead of seven, so twelve search requests a cycle instead of fourteen.
  Neither AI group could be written as plain terms, and that is worth knowing
  before editing them: matching is **substring, not word-boundary**, so a term
  `AI` would match said, maintain, chain, fail, email, training and Ukraine.
  The boundary therefore lives in a `/regex/`, which is run against the
  original title where the capitals also help; the plain terms are all long
  phrases (`artificial intelligence`, `large language model`, `tri tue nhan
  tao`) that are safe as substrings. The primary terms were picked from
  measurement rather than taste: quoted as a phrase, `artificial intelligence`
  returned 6 relevant hits of 6 on HN Algolia and `open source AI` returned 6
  open-source AI projects of 6, where a bare `LLM` returned 3 of 6. A
  side-effect worth recording: the eight fixed feeds had contributed **zero**
  matches across the store's first twenty runs, because every group was an
  English embedded term while more than half the fixed items are Vietnamese
  consumer tech - the AI group is broad enough that `hn`, `lobsters` and
  `hackaday` now land on the page for the first time
- **ai**: the day's matches now get a summary, one line per keyword group - the
  group's name and at most two sentences about what actually stood out in it,
  in Vietnamese. It sits above the stories on the page and is rewritten every
  cycle; the same line-per-topic text goes to Telegram and Discord **once a
  local day**, at or after `ai.notify_at_hour`, because a page is somewhere you
  go and a message is something that interrupts you - forty-eight interruptions
  a day saying roughly the same thing is how a channel gets muted, taking the
  outage alerts with it. A group whose day held nothing notable is left out of
  the prompt entirely rather than given a sentence saying so, which is what
  keeps the message a glance. "Once a day" is not remembered in memory: the
  summary rides in the existing `reported` table under `summary:<local date>`,
  per channel, so a container that restarted at noon still knows this morning's
  went out. This task (P6-4) had been recorded as deliberately not built,
  against an API key, a per-run bill and a third runtime dependency - and one
  of those three had quietly expired: `Fetcher.post_json()` already exists, so
  an OpenAI-compatible `/v1/chat/completions` is a POST with a bearer header
  and **no new import**. The other two are opt-in, `ai.enabled` shipping
  `false`, so a config that says nothing about `ai` upgrades untouched and
  never reaches the network. Naming the wire format rather than a vendor is
  what makes the bill optional too: OpenRouter, DeepSeek, Groq and a local
  Ollama all answer the same endpoint - and none of those needs a key, so an
  unset `OPENAI_API_KEY` sends no `Authorization` header at all rather than an
  empty bearer token, and `ai.enabled: true` without one starts fine. That is
  where this section parts company with the notification channels, which are
  fatal without their secrets: a channel cannot work without one, while
  refusing to start here would be the config telling you your own LAN server
  does not exist. And it may never cost a cycle -
  `summarize()` has exactly one failure mode, no summary, and a refused
  endpoint adds nothing to the run's problem list, so it can neither withhold
  the heartbeat ping nor trip an ops alert
- **fetch**: `post_json()` takes caller-supplied headers, which is what lets an
  authenticated endpoint be talked to without a second HTTP client in the tree.
  They are merged *underneath* the transport's own rather than over them, so a
  caller can add a header and can never take one away - losing the User-Agent
  to a typo is the 403 on both Reddit sources arriving from a new direction
- **ops**: a run that fails silently is now visible. A radar cannot report its
  own death - a killed container, a host that lost power and a daemon that never
  came back all look identical from inside: silence. So each clean cycle GETs a
  dead-man's switch (`ops.heartbeat_url`), and the alarm is the ping that stops
  arriving. Immediately before it, the crawl fetches its own published page
  (`ops.site_url`): a non-200 withholds the ping and counts the cycle as failed,
  which is what finally notices the tunnel connector going away while every
  other log line still says success. A ping is a claim that the cycle worked, so
  `crawl()` now returns the reasons it should not be called one - a storage or
  render failure, an unusable keyword file, or every enabled source failing at
  once, none of which used to be more than a line in a log nobody reads. The
  reverse is deliberate too: a monitor that refuses the ping is a warning and
  never an alert, because the radar is fine and the thing that would have told
  you so is the thing that broke. Those same reasons now arrive on Telegram and
  Discord: **two** failed cycles in a row send one message naming them, and the
  first clean cycle after sends one saying it recovered - two messages for an
  outage of any length, because a broken thing repeats every thirty minutes and
  an alert that repeats with it is one you learn to swipe away, taking the next
  real one with it. The alert takes a different escaping rule than a story does
  on each channel: Telegram gets no `parse_mode` at all, so a stray `<` in an
  exception message cannot cost the one message you must not lose, while Discord
  is escaped because it renders Markdown in plain content whether asked to or not.
  Sending an alert logs one `alerted N of M channel(s)` line at `WARNING`,
  including when every channel took it - found by the live run, where a
  successful alert left no trace in `docker logs` but an unexplained two-second
  gap, and the quietest thing in the file should not be the feature whose whole
  purpose is visibility
- **ops**: the store has a backup - one dated copy per day under `backups/`,
  taken with SQLite's own online-backup API rather than by copying the file,
  because the crawl holds the connection open and a `-wal` mid-flush can produce
  a filesystem copy that opens cleanly and is missing the last write. It is
  written under a `.part` name and renamed into place, so an interrupted backup
  is never left looking like a good one, and the newest `ops.backup_keep` are
  kept - the filename *is* the rotation key, so nothing has to parse a name back
  into a date. Two orderings carry the weight: the copy is taken **immediately
  before** the prune and inside the same guard, so a store that cannot be backed
  up is never pruned either; and `backups/` sits outside `storage.data_dir`
  entirely, mounted only into the crawl service, because Caddy serves that
  directory to the public web and a dated copy of the whole archive in it would
  be one Caddyfile line from being downloadable by anyone with the URL. Restore
  stays a documented three-command procedure rather than a flag on the one
  process that must not be running while it happens
- **ops**: the archive has a ceiling - the shipped `config.yaml` now sets
  `storage.retention_days: 90` instead of `0`, so `news.db` and `output/days/`
  stop growing without bound. The *default* for an absent key stays `0`: an
  existing deployment that never mentioned the key must not start deleting rows
  because it was upgraded. A new `ops` section carries the four keys the rest of
  this entry needs - `heartbeat_url`, `site_url`, `backup_dir` and
  `backup_keep` - and all four ship inert or safe, so a config written before
  this version runs unchanged. A mistyped heartbeat url is refused at startup
  rather than at the moment it was supposed to save you: a url that silently
  never reaches its monitor is one more place for exactly the failure the
  heartbeat exists to catch
- **deploy**: the tunnel - `https://news.dtbao.org` now serves the report. The
  Cloudflare Tunnel connector runs as a `cloudflared` service inside the compose
  stack rather than on the host, which is what lets the origin be `caddy:8080`
  at all: a tunnel running on the host cannot resolve a docker service name, and
  restarting one that already carries other hostnames costs those too. The
  ingress is a committed file (`docker/cloudflared.yml`) because a tunnel id is
  not a secret; only `docker/tunnel-credentials.json` is, and it is gitignored.
  The service sits behind the `tunnel` compose profile, so a checkout without
  that credentials file starts exactly what it started before instead of a
  container crash-looping on a missing mount. `scripts/setup.py` adds
  `--profile tunnel` by itself when it sees the credentials file, so installing
  is still the same two steps on a machine that publishes and on one that does
  not
- **crawl**: the senders - a cycle that finds something new now pushes it to
  Telegram and Discord instead of only writing the page. Only what is **new**
  goes out: the run is read back out of the store, diffed against the per-channel
  seen-set, and a story is recorded as sent only after the message carrying it
  was accepted - so a crash between the two re-sends rather than losing it, and
  enabling Discord later does not replay everything Telegram already had. A
  cycle with nothing new sends nothing at all rather than an empty message.
  `report.mode` finally does something: `incremental` pushes this run's new
  matches, `current` pushes the whole shortlist every cycle, `daily` pushes
  everything today that has not gone out yet. Messages are split at a group
  boundary first and an item boundary second, never through the middle of a
  story, and every title is escaped for the channel it is going to - Telegram's
  HTML and Discord's Markdown break on different characters, and an unescaped
  one costs the whole message rather than one headline. A throttled channel is
  slept for exactly as long as it asked (`Retry-After`, capped at a minute)
  instead of a guess, and a refused channel costs neither the page nor the
  other channel
- **crawl**: the store and the page - `python -m news_radar --once` now writes
  what it found instead of only printing it. Every shortlisted story lands in
  `output/news.db`, keyed by the same dedup key the ranking uses: the row keeps
  the date it was first seen, the earliest timestamp any source reported for it,
  and the accumulated set of sources that carried it, so a story re-found
  tomorrow is the same row rather than a second one. The page is then rendered
  from the **store**, not from the run in memory - it shows the whole local day,
  which is what makes a restart at noon still publish what the morning found.
  `output/index.html` and an immutable `output/days/<date>.html` are written each
  cycle: one section per keyword group in the keyword file's own order, empty
  groups included, the first `report.rank_threshold` of each highlighted, and
  every title, link and source escaped on the way in. The page carries a dark
  mode that remembers the choice, a search box that folds diacritics the way the
  matcher does, and links to every past day - with no external stylesheet,
  script or image, so it still reads when the network it reports on is down.
  `storage.retention_days` prunes rows and day files past the window in the same
  pass, `0` keeping everything. A locked database or a full disk costs the page,
  never the fetch. Nothing is notified yet
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

- **caddy**: the SQLite store is no longer downloadable from the site.
  `output/` holds `news.db` next to the pages because the crawler writes one
  volume, and the file server was handing it to anyone who asked for
  `/news.db` - the whole archive in a single request - while `browse` published
  a listing of everything else in the directory. Requests for the store and its
  `-wal` / `-shm` / `-journal` siblings now answer `404`, and directory listing
  is off; `index.html` already links every day snapshot, so nothing a reader
  needs was behind it. Worth taking before `news.dtbao.org` reaches the public
  internet in P5
- **config**: both shipped search templates now ask for recent stories rather
  than relevant ones, so the freshness half of the ranking finally does
  something. Google News takes a `when:7d` window and Hacker News is queried
  through `search_by_date` with `tags=story`; before this every search hit
  scored exactly the source term and the order inside a group was arbitrary.
  Measured against the shipped keyword file: ten stories now clear that floor
  where none did. It costs volume on Google News - the Vietnamese index holds
  almost no recent embedded coverage, so seven queries return sixteen items
  instead of two hundred and fifty three - but the items that were dropped were
  three to eight months old and were filling whole groups
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
