---
title: Active Context
updated: 2026-09-06
---

# Active Context

> What is being worked on right now. Read first every session; rewrite when the focus shifts. Transient - not a durable fact.

## Current focus

**The upgrade path is the current work (2026-09-06, after v0.2.2).** Asking how
a version update is handled found a procedure that existed, described a
production this one is not, and promised a check nothing performed. Four
changes, all unreleased on `release/v0.2`: `setup.py --check` now names config
keys the template has and the local file lacks (and fails on a missing
destination file), `store.open_db()` refuses a store between `0` and
`SCHEMA_VERSION` instead of returning it, `config/frequency_words.txt` became a
local file created from a committed `.example`, and `## Updating` in
[[setup-homelab]] was rewritten for the detached-tag production that actually
runs. **The next deploy is the awkward one**: it is the checkout that deletes
`config/frequency_words.txt`, and the `--check` that warns about it only exists
on the far side of that same checkout.

**Three defects reported off the live site were fixed on `release/v0.2`
(2026-09-06)**, all three landing after v0.2.1 and none of them yet on
`news.dtbao.org`: a day page whose day list 404'd (`/days/days/<date>.html`), a
story link that replaced the report instead of opening beside it, and
Telegram/Discord messages that disagreed with the page in both content and
membership. `render.py`, `notify/` (all three files), `__main__.py`,
`config.yaml.example` and three test files changed. **Nothing is live until
`release.py 0.2.2` and a homelab redeploy**, and `report.mode` needs a hand edit
there on top - see Next steps.

**The page was redesigned on 2026-09-06**, after v0.2.0 and against a real day
pulled out of the store rather than a mockup. Five candidate layouts were built
and thrown away except one: a sticky rail beside a single column of stories, in
a container 80% of the viewport wide. The story row lost its score and its
source ids - the operator asked what `0.74` was, which is the answer to whether
it earned its place. `render.py` and `tests/test_render.py` are the only source
files that changed; the fetch, selection, store and notify layers are untouched.

**Still open from P6** (unchanged by the redesign):

**P6 Ops is built, P6-4 included** (2026-09-05). A cycle that fails now says
so - twice per outage, on Telegram and Discord - and a cycle that stops
happening at all trips a dead-man's switch that lives outside this stack. The
store gets a dated backup before anything is pruned, and the archive has a
90-day ceiling. The day's matches also arrive as a paragraph now: one line per
keyword group, on the page every cycle and on the phone once a local day.

**What is left of P6 is time, not code.** Seven days unattended with no manual
intervention and no disk growth is the phase's definition of done, and the clock
starts when this branch merges.

## Recent changes

- **The upgrade work landed in thirteen commits on `release/v0.2`**
  (2026-09-06): `scripts/setup.py` (`template_keys()`, `missing_config_keys()`,
  `ensure_file(..., verify=)`, a third `TEMPLATES` pair), `src/news_radar/store.py`
  (`open_db()`'s fourth branch), `.gitignore`, the rename to
  `config/frequency_words.txt.example`, `tests/test_setup.py`,
  `tests/test_store.py`, `tests/test_keywords.py`, `tests/test_filter.py`,
  `README.md`, and five bank docs.
- **A documented promise nothing implements is worse than an undocumented gap.**
  `cli-scripts.md` had claimed for months that `--check` catches a key added
  upstream. Believing it is what let `report.mode` sit stale through a release.
  Both halves of that sentence are now code, and both are tested.
- **`git checkout <tag>` is a deploy step with side effects.** It deletes a path
  the new commit does not carry - which is how the keyword-file split breaks the
  next upgrade, and why that entry is a `### Breaking Changes` rather than a
  `### Features`. Proven on a throwaway clone, not reasoned about.
- **`skill-support-commit` cannot commit a pure untrack.** `git rm --cached`
  leaves the file byte-identical on disk, so the skill's `git reset` baseline
  re-tracks it and `git add` finds no diff; it stopped cleanly and said so. That
  one commit (`34138b5`) was made by hand. Worth knowing before the next rename.
- **The three live defects landed in ten commits on `release/v0.2`**
  (2026-09-06): `render.py` (`_day_nav()` takes a prefix, `write()` renders once
  per destination, `_story()` gains `target="_blank"`), `notify/__init__.py`
  (`stamp()`, `TIME_FMT`, `NO_TIME`, `UTC`), `notify/telegram.py` and
  `notify/discord.py` (`_line()`, `build()`, `send()` all take `tz`),
  `__main__.py` (`_rows_to_send()`, `_send_channel()` and both `SENDERS`
  wrappers take `tz`; `_notify()` resolves it once), `config.yaml.example`, and
  `tests/test_render.py`, `test_notify.py`, `test_config.py`.
- **Two files that are identical are two files that cannot both be right.**
  `index.html` and `days/<today>.html` shared their bytes, and the day list is
  the one block whose correctness depends on where the file sits. The general
  shape: a relative href is a fact about the *file*, not about the page.
- **A `rel` with no `target` is a comment.** `rel="noopener noreferrer"` had
  been on every story link since P3 doing nothing at all - it only means
  something next to `target="_blank"`. Half a pattern reads as the whole one on
  review.
- **The messages and the page had drifted apart the moment the page changed.**
  v0.2.1 took the source ids off the page and put a timestamp on it; nothing
  told `notify/`, and there was no test that could have. The one now in
  `test_notify.py` compares `notify.stamp()` against `render._when()` directly,
  so the two halves of layer 5 cannot spell a timestamp differently again.
- **`incremental` loses a story the channel refused.** The next cycle reads its
  own run and the story is not in it. `daily` re-offers it, which is the
  argument for the template change independent of matching the page.
- **The page redesign touched two files** (2026-09-06): `src/news_radar/render.py`
  (`STYLE` rewritten, `_slug()` and `_jump_nav()` new, `_story()`, `_group()` and
  `_page()` rebuilt) and `tests/test_render.py`. `write()` keeps its signature,
  so `__main__.py` did not change.
- **An author `display` beats the browser's `[hidden]`.** The single most
  expensive thing learned here: `li.story { display: grid }` silently disables
  `[hidden] { display: none }`, and the search box would have filtered nothing
  on a page that looked perfect in a screenshot. Anything that gives a filtered
  element a `display` needs `[hidden] { display: none !important; }` with it.
- **A screenshot is not a check.** The theme toggle looked wrong in one capture
  and right in another; measuring `getComputedStyle(body)` before and after the
  click settled it in one command. Headless Chrome also reports a different
  `prefers-color-scheme` between `--screenshot` and `--dump-dom` runs, so the
  colour in a capture is not evidence of which branch fired.
- **Removing something from the page is a test change, not a deletion.**
  `test_render.py` pinned "the score is on the page"; it now pins that the score
  is *not*, so the decision is defended rather than merely applied.
- **P6 landed in twenty-one commits on `release/v0.1`** (2026-09-05):
  `src/news_radar/ops.py` (new - `heartbeat()`, `Health`, `ALERT_AFTER`),
  `store.py` (`backup()`), `notify/telegram.py` and `notify/discord.py`
  (`alert()`), `__main__.py` (`crawl()` returns `(ranked, problems)`,
  `_dead_sources()`, `ALERTERS`, `_alert()`), `config.py` (the `ops` section),
  `config/config.yaml.example`, `docker/docker-compose.yml`, `.gitignore`,
  `Dockerfile`, and `tests/test_ops.py` (new).
- **A ping is a claim that the cycle worked**, and that one sentence decided the
  whole shape of P6-1. The published page is fetched *before* the ping and any
  problem anywhere withholds it, so silence is the signal - which is the only
  thing that can survive the container being killed.
- **The site check is what closes the tunnel gap.** `progress.md` had carried
  "nothing yet alerts on it" as a known issue since P5; the crawl now fetches
  `https://news.dtbao.org/` every cycle, so a connector that deregistered is a
  failed cycle rather than something you find out about days later.
- **Two messages per outage, not one every thirty minutes.** `ALERT_AFTER = 2`
  and the recovery message are the whole of `ops.Health`. An alert that repeats
  alongside the thing it is reporting is one you learn to swipe away, and the
  next real one goes with it.
- **The live run found a hole the tests could not.** A *successful* alert logged
  nothing at all - the only trace in `docker logs` was an unexplained two-second
  gap. `_alert()` now logs `alerted N of M channel(s)` at WARNING, which is also
  what proved both channels accepted the message.
- **`backups/` is outside `output/`, not merely excluded from it.** Caddy roots
  on `output/`; a dated copy of the whole archive there would be one Caddyfile
  line from public. The bind mount is on the crawl service only.
- **The retention default and the retention template deliberately disagree.**
  `config.py` keeps `0` so an upgrade never starts deleting rows nobody chose to
  lose; the shipped template says `90` because someone chose it.
- **P6-4 landed on `release/v0.1` after being dropped** (2026-09-05):
  `src/news_radar/summarize.py` (new - `summarize()`, `build_prompt()`,
  `daily_key()`, `SENTENCES_MAX`), `fetch/http.py` (`post_json()` takes
  `headers`), `config.py` (the `ai` section), `render.py` (`_summary()`, the
  `summary=` argument), `__main__.py` (`_summarize()`, `_send_summary()`,
  `_publish()` returning `(run_id, summary)`, `_fetcher()`'s timeout override),
  `config/config.yaml.example`, `docker/.env.example`,
  `docker/docker-compose.yml`, and `tests/test_summarize.py` (new).
- **One third of the reason to drop P6-4 had quietly expired.** The recorded
  objection was an API key, a bill and a third runtime dependency - but P4 had
  already added `Fetcher.post_json()`, so an OpenAI-compatible
  `/v1/chat/completions` is a POST with a bearer header and no new import. The
  other two are opt-in. Worth remembering as a shape: a decision written down
  with its reasons can be re-checked against the reasons, which is the whole
  argument for writing them down.
- **Per topic, not one blob - and the phone gets it once a day.** A group with
  nothing notable is left out of the prompt entirely rather than told to say
  "nothing today", and two sentences a topic is a hard bound in the prompt. The
  page is rewritten every cycle; the message goes at `ai.notify_at_hour`, kept
  to once by `summary:<local date>` in the existing `reported` table, so a
  restart does not re-send it.
- **The summary may never speak for the cycle.** `summarize()` has one failure
  mode, `None`, and the caller adds nothing to `problems` - a dead endpoint
  cannot withhold the heartbeat ping or trip an ops alert. Same asymmetry as
  P6-1's refused ping: the optional thing does not get to report on the thing
  that is not.
- **P5 landed in four commits on `release/v0.1`** (2026-09-05):
  `docker/cloudflared.yml` (new, the ingress), `docker/docker-compose.yml` (the
  `cloudflared` service behind `profiles: ["tunnel"]`), `.gitignore`,
  `scripts/setup.py` (`compose_argv()` takes a `root` and detects the
  credentials file), `tests/test_setup.py` (new).
- **The bank was wrong about the tunnel and P5 corrected it.** It described a
  tunnel *container* the homelab already ran for `mcp.dtbao.org`, to be attached
  to this project's network. Reality: cloudflared runs here as the Windows
  service `win-dev`, carrying `ssh.dtbao.org` and `remote.dtbao.org`. A host
  connector cannot resolve `caddy`, so the connector had to move into the stack
  for the documented `http://caddy:8080` origin to exist at all.
- **The route was already there; the connector was not.** `news.dtbao.org` was
  a DNS record pointing at a tunnel named `news` that had never been run - the
  site answered Cloudflare `1033`. All of P5-3 was starting the container.
- **P4 landed in eight commits on `release/v0.1`** (2026-09-05):
  `fetch/http.py` (`post_json()`, `Retry-After`), `store.py` (`run_matches()`),
  `notify/__init__.py` (`SendResult`, `pick`, `chunk`, `clip`),
  `notify/telegram.py`, `notify/discord.py`, and `_notify()` in `__main__.py`.
- **The senders read the store, not `ranked`** - the same choice P3 made for the
  page, for the same reason. The story that goes out carries the same score and
  the same source list as the one on the page, and `report.mode` only changes
  *which window* is read: `run_matches()` for `incremental` and `current`,
  `day_matches()` for `daily`.
- **`report.mode` finally does something.** It was validated by `config.py` from
  P0 onward and read by nothing; `mode: daily` was accepted and silently
  ignored. All three modes now behave as the config comment claims.
- **The transport learned to POST, and learned to read `Retry-After`.** Both
  changes live in `Fetcher` rather than in `notify/`, so the GET path gets the
  429 fix too - Google News throttles as readily as a bot API does.
- **One deliberate widening of the layering rule**: `notify/*` imports layer 1.
  Recorded in [[module-layout]] and [[notify-channels]] rather than left to be
  discovered.
- **Two departures from the drafted contract, both recorded in
  [[notify-channels]]**: `send()` takes no `RunMeta` (nothing consumed it), and
  the secrets are read in `__main__` rather than inside each channel (which is
  what lets both channels be tested with no environment at all).

Before this session: P3 landed the store and the page, P2 the selection layer,
P1 the whole fetch layer, P0 the release tooling, the docker stack, the config
loader and the design bank - see `progress.md`.

## Next steps

1. **Cut the next version and deploy it in one visit.** v0.2.2 is tagged and
   pushed but not deployed, and everything since is untagged. Cut it
   (`python scripts/release.py 0.2.3`), then on the homelab follow `## Updating`
   in [[setup-homelab]] - and expect that checkout to delete
   `config/frequency_words.txt`, because that is the release that splits it.
   `python scripts/setup.py` (no flags) puts it back from the `.example`.
2. **Edit `report.mode` on the homelab by hand, in the same visit.**
   `~/news-radar/config/config.yaml` is gitignored and still says `incremental`;
   no template change can reach it, which is what the new `--check` will tell
   you. Set `mode: daily`. Expect a small burst on the first cycle after it -
   every story of the current day the channel has not already been told about
   goes out at once.
3. **Point `ops.heartbeat_url` at a real monitor.** It ships empty, so the half
   of P6-1 that survives the container being killed is built but not armed. A
   healthchecks.io ping url or an Uptime Kuma push url in `config/config.yaml`
   (gitignored) is the whole change - no code, no restart of anything else.
4. **Let it run seven days.** That is P6's definition of done and the only thing
   still open. On day seven: the crawl container still `Up` with no restart,
   `backups/` holding one file per day and no more, the day list capped at 90,
   and however many alerts arrived being ones you would have wanted.
5. **Watch whether `ALERT_AFTER = 2` is the right chattiness.** Every alert so
   far came from a `site_url` pointed at a 404 on purpose; real feed flakiness
   has not been through it yet.
6. **Retention will actually delete something for the first time** once the
   store holds anything older than 90 days. A backup is written immediately
   before each prune, so the first one has a copy standing in front of it.
7. **Still worth eyeballing from P4**: whether 5 Discord messages per cycle is
   pleasant or noisy, and whether any real headline trips an escaping case the
   fixtures missed.

## Active decisions

- **A ping is a claim that the cycle worked.** It is never made before the
  published page has answered, and any problem anywhere in the cycle withholds
  it. A heartbeat that fires regardless of outcome is worse than none: it
  actively reports health that is not there.
- **Silence is the signal, and it has to be read from outside.** A killed
  container, a host that lost power and a daemon that never came back are
  indistinguishable from inside the process. That is why P6-1 is a dead-man's
  switch rather than an internal check.
- **A refused ping is a warning, never an alert.** The radar is fine and the
  thing that would have told you so is what broke. Alerting on it is how you
  train yourself to ignore the alert.
- **Two messages per outage, whatever its length** - one at `ALERT_AFTER = 2`
  consecutive failures, one on the first clean cycle after. `Health` lives in
  memory and dies with the process on purpose: a container that restarted has
  lost the context that made the first alert true, and re-arming means a
  crash-looping stack says so again rather than going quiet forever.
- **No backup, no deletion.** `store.backup()` runs immediately before
  `store.prune()` inside the same guard, so a store that cannot be copied is
  never pruned.
- **`ops.backup_dir` is never under `storage.data_dir`.** Caddy roots on that
  directory; a dated copy of the whole archive in it would be one Caddyfile line
  from public. `store.py` cannot enforce this - it does not know what is being
  served - so it is a config rule.
- **A default is what an *absent* key falls back to, and must be the harmless
  value.** `storage.retention_days` defaults to `0` and the template ships `90`:
  an upgrade that never mentioned the key must not start deleting rows nobody
  chose to lose. The same rule flushed four wrong Default-column rows out of
  `config-and-env` when it was verified.
- **No `HEALTHCHECK` in the Dockerfile, deliberately.** It would only colour a
  column in `docker ps` - nothing restarts an unhealthy container without an
  autoheal sidecar, and that is a new moving part for a failure this stack has
  not had.
- **A story is marked sent only after the message carrying it was accepted.** A
  crash between the send and the write re-sends next cycle; a duplicate is the
  acceptable failure where a silently dropped story is not. `mark_reported()`
  after the sender returns, never before.
- **A refusal ends the channel for that run.** The same answer is coming for
  chunk two, and hammering a throttled bot is how throttled becomes banned.
  Whatever was accepted before the refusal still counts as sent.
- **Two guards around notification, and both are needed.** The outer one keeps a
  locked store from costing the page; the inner one is per channel, because the
  contract says a dead webhook must leave the other channel still attempted.
- **The page is rendered from the store, not from `ranked`.** A
  `render.write(..., ranked)` anywhere is a bug, not a shortcut.
- **A message line is the page's line.** Same fields, same order, same
  timestamp spelling - a phone showing the same story differently is a second
  report, and the reader has to reconcile two things that were meant to be one.
  When the page's story row changes, `notify/` changes in the same commit.
- **A local file is one a release may not overwrite.** `config.yaml`,
  `frequency_words.txt` and `.env` are the deployment's, not the repository's;
  each ships as a committed `.example` that `setup.py` copies once. A release can
  only *tell* you what it added - which is what `setup.py --check` is for, and
  why there is no config migration and is not going to be one.
- **A promise in the bank is a promise the code has to keep.** `--check` was
  documented for months as catching a key added upstream and never did, and a
  deployment ran a whole release on a stale value because the doc was believed.
  A doc sentence that describes behaviour is a test that has not been written.
- **A relative href is a fact about the file, not about the page.** Two output
  files at two depths cannot share one nav. `index.html` and `days/<date>.html`
  differ in exactly that block and nowhere else.
- **Layer 3 and layer 4 import no config and read no clock.** The weights, the
  `{source_id: rank_weight}` map, the data directory, the retention window and
  `now` are all arguments `__main__.py` builds. It is why ten of the twelve test
  files run with nothing installed.
- **Everything off a feed is escaped at the boundary it is crossing.** The page
  escapes for HTML, Telegram for its own HTML subset, Discord for Markdown - and
  the three sets of dangerous characters are not the same one. A feed title is
  somebody else's text arriving unreviewed every thirty minutes.
- **The page needs no network to be read.** Inline CSS and JavaScript, no
  external stylesheet, script or image - `test_render.py` asserts it rather than
  trusting it.
- **Clean-room from TrendRadar.** It is a reference to consult when stuck, never
  a source to copy from - it is GPL-3.0. `rule/reference-trendradar.md` says
  where to look by problem and what may not cross back.
- **Two runtime dependencies, total**: `pyyaml` and `feedparser`. HTTP, storage,
  templating and both senders come from the standard library. A third needs
  justifying in the changelog. P4 held the line - the channels are `urllib` and
  `json`.
- **One guard, not one per caller.** `feeds.read_source()` is the only place a
  source failure is caught; `_publish()` the only place a storage or render
  failure is; `_notify()` the only place a send failure is.
- **The changelog records technical changes only**, written by hand into
  `## Unreleased` in the same commit as the change. One entry per change, not
  per commit: all of P4 is one `**crawl**` line.
- **Both scripts stay stdlib-only** so they run on a bare checkout, before
  anything is installed.
- **Self-hosted, not GitHub Pages.** The crawl and the site both run on the
  homelab; `news.dtbao.org` is reached through a Cloudflare Tunnel whose
  connector is a container **in this stack**, not on the host. A host connector
  cannot resolve `caddy`, and restarting one that carries other hostnames costs
  those too.
- **A tunnel id is not a secret, a credentials file is.**
  `docker/cloudflared.yml` is committed; `docker/tunnel-credentials.json` is
  gitignored. The `tunnel` compose profile keeps a checkout without that file
  from ever starting the connector.
- **Secrets live only in `docker/.env`.** `config.yaml` is committed as a
  template and a leaked copy must be harmless.
