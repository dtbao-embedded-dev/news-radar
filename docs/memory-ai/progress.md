---
title: Progress
updated: 2026-09-07
---

# Progress

> Current delivery state - what works, what's left, known issues. Update at every checkpoint (feature shipped, milestone, direction change).

## What works

### The AI summary runs for real, on OpenRouter (2026-09-07)

`ai.*` had been built, tested against a local stub, and never pointed at a real
model. The homelab now runs it: `api_url:
https://openrouter.ai/api/v1/chat/completions`, `model:
minimax/minimax-m3:free`, `OPENAI_API_KEY` in `docker/.env`. First cycle after
the change, no retries:

```
INFO  summary: 1576 character(s) over 5 topic(s)
INFO  rendered output/index.html (6 group(s), 76 story(ies))
INFO  summary: sent to 2 of 2 channel(s) [telegram, discord]
INFO  heartbeat: http://caddy:8080/ answered
```

- **Two sentences a topic reads as a summary, not a horoscope.** That was the
  open question this file carried. The model picked the notable story out of
  each group and said why it mattered rather than restating the headline, in
  Vietnamese as `INSTRUCTION` asks. The page carries five `<p>` blocks in the
  keyword file's own group order.
- **Five topics, not six - and the sixth was the right one to drop.** The
  prompt tells the model to omit an unremarkable topic entirely, and it omitted
  `RTOS`. Three of that group's five stories were about Indian Regional
  Transport Offices, because the keyword `RTOS` matches `RTOs` after folding.
  The model routing around a keyword-quality problem is not a fix for it - see
  Known issues.
- **The model was chosen by running the real prompt, not by reading a
  leaderboard.** Today's actual 3085-character prompt was POSTed to two free
  models and the answers compared. `google/gemma-4-31b-it:free` answered
  `429 - temporarily rate-limited upstream`; `minimax/minimax-m3:free` answered
  in 16 s with usable Vietnamese.
- **The once-a-day guard works on the real path too.** `reported` carries
  `summary:2026-09-07` for both channels, so the next cycle sends nothing and
  logs `already sent today`. Verified in the store, not inferred.
- **`.env` needs a container recreate, not a restart.** The plan on file said
  `docker compose restart news-radar`, which is right for `config.yaml` - a bind
  mount read at process start - and wrong for a **new** environment variable:
  Compose bakes those in at container create time, so `restart` reuses the old
  environment and the key never arrives. `up -d` recreates.

### The tunnel is gone; the report is served on the LAN (2026-09-07)

Removed rather than fixed: the `cloudflared` service, `docker/cloudflared.yml`,
`NEWS_RADAR_TUNNEL_ID`, and the credentials-file detection that switched on the
`tunnel` compose profile in `scripts/setup.py`. **`NEWS_RADAR_HTTP_PORT` (8088)
is now the only way to reach the report**, and it is no longer described as
debugging-only.

- **The reason is moving parts, not cost.** A connector carries its own
  credentials, its own upgrade story, and its own failure mode - Cloudflare
  `1033` while every log line in the crawl says success. That is a lot of
  permanent machinery inside a project whose job is to write HTML into a
  directory. Where the report is readable from is now a decision made in front
  of the published port, and changing it touches nothing in this repository.
- **It landed one commit after the tunnel id was parameterised**, which is the
  honest order: laying out every piece a connector needs - config file,
  credentials file, profile, env var, detection rule - is what made the question
  obvious.
- **The tests pin the absence.** No `cloudflared` service, no service declaring
  a `tunnel` profile, no `cloudflared.yml` on disk, and only `caddy` publishing
  a port; `test_setup.py` adds that a leftover credentials file changes nothing,
  which is the check that would actually catch the detection creeping back.
- **`--profile tunnel` still parses and starts nothing extra.** An old command
  in somebody's shell history is harmless rather than confusing - verified:
  `--profile tunnel config --services` lists `caddy` and `news-radar`, the same
  two as no profile at all.
- **`.gitignore` still ignores `docker/tunnel-credentials.json`**, deliberately.
  The path is dead; a machine that still holds one of those files must not be
  able to commit it.

**Torn down on the real deployment the same day** (2026-09-07), and measured at
each step:

- the `news-radar-tunnel` container was stopped and removed - `news.dtbao.org`
  went from `200` to `502` while `http://localhost:8088/` stayed `200`, and the
  crawl and Caddy containers were untouched;
- the `news` tunnel was deleted from the Cloudflare account. Three tunnels
  remain there and none of them are this project's; `git.dtbao.org` and
  `photos.dtbao.org` both still answered `200` afterwards, which is the check
  that the blast radius was one tunnel wide;
- `ops.site_url` was moved to `http://caddy:8080/` on the homelab **before the
  next cycle ran**. It had still been the public URL, so the following cycle
  would have failed on a `530`, and two of those in a row is a real alert about
  a non-problem. The cycle after the restart logged
  `heartbeat: http://caddy:8080/ answered`.

**One loose end is left, and it needs the Cloudflare dashboard.** The
`news.dtbao.org` CNAME still exists and now points at a tunnel that is gone, so
the hostname answers **530** instead of not resolving. `cloudflared tunnel
route` can only *create* DNS records - there is no delete subcommand - so
removing it is a dashboard or API operation, not something this repository can
do.

### The package is an image, and the data is out of its way (2026-09-06)

The previous entry made the upgrade *checkable*. This one makes the failure it
checks for **unreachable**: production stops being a git checkout, so no command
on that machine can delete `config/`, `output/` or `backups/`. Five things, all
on `release/v0.2`:

- **One variable owns every path a deployment holds.**
  `${NEWS_RADAR_HOME:-..}` in `docker-compose.yml`, resolved relative to the
  compose file. Unset it is `..`, the repository root - so a checkout behaves
  exactly as it always did, which is why the default is that and not something
  tidier. A deployment sets `.` and keeps its data beside the compose file.
  **Caddy's `/srv` moved with it**, and that is the mount that was easy to miss:
  left behind, the crawl publishes to one directory while the web server serves
  another, and the site 404s while every log line says success.
- **The crawl service runs a published image.**
  `ghcr.io/dtbao-embedded-dev/news-radar:${NEWS_RADAR_VERSION:-latest}`, with
  `build:` kept beside it so a checkout still compiles what it is editing.
  Compose builds only when the image is absent locally, so a deployment that has
  pulled never builds. One footgun, accepted and documented: `up -d` before
  `pull` on a deployment tries to build and dies on the absent `Dockerfile`. The
  alternative was two compose files that can disagree.
- **A `v*` tag publishes that image.** `.github/workflows/image.yml`,
  `linux/amd64` only because the homelab is `x86_64` (measured, not assumed). It
  refuses a tag the `VERSION` file disagrees with - `VERSION` is baked into the
  image, so a mismatch would have the container report a version that was never
  published. Both guards were exercised locally against the real `VERSION`:
  `v0.2.2` publishes, `v0.2.3` is refused, `0.2.2` and `vX.Y.Z` are refused as
  malformed.
- **The stack updates itself, opt-in and narrowly.** A `watchtower` service
  behind an `autoupdate` profile, polling GHCR once a day and recreating
  **only** the container carrying `com.centurylinklabs.watchtower.enable` -
  which is the crawl and nothing else, because caddy and cloudflared are
  version-pinned and are the two things standing between the report and the
  public internet. Profile gating verified: `config --services` lists two
  services, `--profile autoupdate config --services` lists three. The `:ro` on
  its docker socket is **not** a sandbox and the compose file now says so; the
  narrowing is the label and the profile.
- **`python -m news_radar --check` carries the drift check into the image.**
  Losing the checkout would have lost `setup.py --check` with it, and that check
  is the whole reason `report.mode` cannot sit stale again. The image bakes
  `config.yaml.example` at `/app/config-templates/` - deliberately not under
  `/app/config`, which the deployment's own directory is mounted over. Measured:
  exit `0` against the real `config/config.yaml`, exit `1` naming `report.mode`
  against a copy with that key removed. The two implementations stay separate on
  purpose - `setup.py` may not `import yaml`, the image can.

**Then every "what could break" line was checked, and four of six were wrong**
(2026-09-06, immediately after). The claims written when this shipped were taken
back to the code and to a real docker daemon rather than left as prose:

| Claim as written | Verdict |
|------------------|---------|
| `up -d` before `pull` fails on the absent Dockerfile | **true** - and compose does not fall back to pulling; it goes straight to the build and says `failed to read dockerfile` |
| `git checkout` deletes `config/frequency_words.txt` | **true, but framed backwards** - untouched it is deleted, edited the checkout aborts |
| A wrong `NEWS_RADAR_HOME` "comes up clean, publishes no history" | **false** - it crash-loops on the missing config, and leaves root-owned directories |
| A bad release is reported by P6 within two cycles | **false for the shape that matters** - a container that will not start never builds `ops.Health` |
| Pinning `NEWS_RADAR_VERSION` alone loses to the next poll | **false** - watchtower follows the tag the container runs, and a version tag does not move |
| *(not previously claimed)* the GHCR package is public | **false** - private by default, even from a public repo |

Nine statements across `.gitignore`, `docker/.env.example`,
`docker/docker-compose.yml`, `CHANGELOG.md` and five bank docs were corrected as
a result. The general shape worth keeping: **a "what could break" list written
from reasoning is a set of hypotheses, and this one was 33% accurate.**

**Measured on the homelab rather than reasoned about (R8).** A throwaway compose
project with the same three mounts, a `config/config.yaml` and a 4 KB
`output/news.db`: `up -d`, then `up -d --force-recreate`. The container id really
changed (`8c8c765c84ae` -> `8fe8844cb33e`) and both files came out byte-identical
by `sha256sum`. The mount was proven real in both directions first - the
container listed the host's files, a file it wrote appeared on the host, and the
`:ro` mount refused a write - because a mount that silently mounted nothing would
have made "byte-identical" a claim about nothing.

### The upgrade path, made checkable (2026-09-06, after v0.2.2)

Asking "what happens on a version update" turned up a procedure that existed,
described a production this one is not, and promised a check nothing performed.
Four things came out of it, all on `release/v0.2`:

- **`setup.py --check` finally does what `cli-scripts.md` has always said it
  does.** It names every key `config.yaml.example` has that the local
  `config.yaml` does not, and exits `1`. Missing keys only, never differing
  values: `ops.site_url` and the `ai.*` endpoint are meant to differ on a real
  deployment, and a check that fires every upgrade is one nobody reads. It also
  fails now when a file it is meant to create is absent, instead of printing
  `would create` and calling the checkout ready. This is the check that would
  have caught `report.mode` sitting at `incremental` through a release that had
  moved to `daily`.
- **The key scan is a deliberate non-parser.** `setup.py` runs before anything
  is installed, so it cannot `import yaml`; `template_keys()` reads key paths
  off the indentation, skipping list items so `feeds[].id` never becomes noise.
  Marked `ponytail:` with the upgrade path - swap in `yaml.safe_load` the day
  the script is allowed a dependency.
- **`store.open_db()` refuses a store it cannot migrate.** `0 < user_version <
  SCHEMA_VERSION` fell through all three branches and returned a connection to a
  file whose shape the build did not match. Unreachable today (`SCHEMA_VERSION`
  is `1`) and that is the point: the day someone bumps the constant is now a
  loud one, with an error naming both versions and saying to write the migration
  first.
- **The keyword file is a local file now, like `config.yaml`.**
  `config/frequency_words.txt.example` ships; the working copy is gitignored and
  created by `setup.py`. It holds no secret - the reason is that a tracked file a
  deployment edits cannot survive `git checkout <tag>`. **The original wording
  here was wrong and a later measurement corrected it** (2026-09-06): it said
  tuned groups were one deploy away from being *silently reverted*, and the two
  real outcomes are opposite. Checking the new commit out over `v0.2.2` with the
  file untouched **deletes** it, and `setup.py --check` then names it and exits
  `1`; with the file **edited**, git refuses the checkout altogether (`error:
  Your local changes to the following files would be overwritten by checkout ...
  Aborting`) and the upgrade stops with nothing changed. So the untuned case
  loses the file and the tuned case blocks the deploy - until somebody reaches
  for `git checkout -f` and loses it anyway. Untracking removes both.
- **`## Updating` describes the production that exists.** It said `git pull` on a
  machine running a detached tag, where `git pull` cannot work. It now carries
  the four real commands, why `--build` is not optional (`Dockerfile` copies
  `VERSION` and `src/` into the image), and a table of what a checkout changes
  and what it cannot touch.

### Three post-redesign defects, closed (2026-09-06)

All three were reported off the live site, not off a test, and all three were
verified against the real thing rather than a screenshot.

- **A day page's day list reached `/days/days/<date>.html` and got a 404.**
  `index.html` and `days/<today>.html` were byte-identical, and a relative href
  resolves against the file carrying it - so the one nav that was right at the
  root was wrong one directory down. `_day_nav()` now takes the prefix and
  `write()` renders the page once per destination; the two files differ in that
  block and nowhere else, which `tests/test_render.py` pins by inverting the
  assertion that used to demand they be identical. Confirmed on the live page
  before the fix: `<a href="days/2026-09-06.html" aria-current="page">`.
- **A story replaced the report instead of opening beside it.**
  `rel="noopener noreferrer"` had been on every story link since P3 - it is the
  half of the pair that closes `window.opener`, and it had been sitting there
  without the `target="_blank"` that makes it mean anything. Only story links
  get it; `nav.jump` and `nav.days` move around this same report and stay in the
  tab, which the test pins separately.
- **Telegram and Discord disagreed with the page in both directions.** Each
  line still carried the source ids the page dropped in v0.2.1 and carried no
  time where the page shows one, and `report.mode: incremental` only ever read
  the run it was called for. Both halves are fixed: `notify.stamp()` renders
  `published_at` exactly as `render._when()` does (`--` and all), the display
  zone is threaded from `app.timezone` through `_notify()` into both channels,
  and the shipped template moves to `report.mode: daily` - the same local-day
  window the page renders. Measured through the real `_notify()` chain against
  a local stub: `• <a href="...">ESP32-S3 ra ban 5.5</a> <i>09:30 06/09</i>` on
  Telegram and ``• [ESP32-S3 ra ban 5.5](...) `09:30 06/09` `` on Discord, from
  a row stored at 02:30 UTC with `hn_algolia` in `item_sources` and no source id
  in either message.
- **`incremental` had a hole `daily` closes.** A story matched by one cycle and
  refused by the channel was never offered again: the next cycle reads its own
  run, and the story is not in it. This was the argument for the template
  change, over and above matching the page.

**P0 Foundation is released as v0.1.0; P1 Fetch, P2 Filter and rank, P3 Store
and render, P4 Notify and P5 Deploy are complete, and P6 Ops is built**
(2026-09-05). See `architecture/delivery-phases.md` for the phase map and the
finished-product definition all of it serves.

### Page redesign (2026-09-06)

- **The report is a rail beside a column now, at 80% of the viewport.** What
  used to be a header and a footer wrapped around 62rem of cards is a sticky
  `aside` - the run's numbers, the filter, every group with its count, the day
  list - beside one column of stories. Below 900px the container widens to 92%
  and the rail stops sticking. Verified at 1920 and at 500: `scrollWidth ==
  clientWidth`, so nothing overflows sideways at either size.
- **A story is its title and its timestamp, nothing else.** The score and the
  source ids were dropped from the page after the operator asked what `0.74`
  meant. Both survive in the store, and the score still orders the list - see
  [[news-item]] for the contract and the two consequences.
- **The one bug this could have shipped, caught before it did.** `li.story` is a
  grid, and an author `display` beats the browser's own `[hidden] { display:
  none }` - so the search box would have hidden nothing at all. Fixed with
  `[hidden] { display: none !important; }`, proven by driving the real filter in
  a headless browser, and pinned by `tests/test_render.py`.
- **Both theme directions measured, not assumed.** `getComputedStyle(body)`
  before and after clicking the toggle, in both starting states: background and
  text swap and `data-theme` is set. All three palette declaration sites
  (`:root`, the media query, `[data-theme]`) were exercised.
- **Two assertions in `test_render.py` were inverted, not deleted.** The suite
  used to pin "the score is on the page" and "the sources are on the page";
  it now pins that neither is, so the removal cannot drift back by accident.

### P6 - Ops

- **`r_embedded` is alive again, and the bank was wrong about why.** This file
  used to carry it as a known issue reading "fixing it means the homelab's DNS,
  not this repository" - and that last clause was the mistake. `www.reddit.com`
  did fail to resolve on the host as well as in the container, but the crawl
  does not have to borrow the host's resolver: `dns: [1.1.1.1, 8.8.8.8]` on the
  crawl service in `docker-compose.yml` fixes it inside this repository. Two
  dead ends are recorded in [[news-sources]] so nobody tries them twice -
  `reddit.com` resolves and 301s to the name that does not, and
  `old.reddit.com` resolves and serves 350 kB of HTML instead of the feed.
  Measured 2026-09-05 after the change: `fixed feeds: 233 item(s) from 8
  source(s)`, `r_embedded 25 item(s)`, **0 sources failed** - the first cycle in
  this project's life where every configured source answered.

- **The day now arrives as a paragraph, not only as a list.** P6-4 shipped:
  `summarize.py` writes one line per keyword group - the group's name and at
  most two sentences about what stood out - above the stories on the page, and
  sends that same text to Telegram and Discord once a local day. Measured on
  2026-09-05 against a local stub endpoint driving a real `--once` cycle: with
  `ai.enabled: false` no request left the process and the page carried no
  summary block; enabled, the page carried it and the log said
  `summary: sent to 2 of 2 channel(s) [telegram, discord]`; a second cycle in
  the same local day logged `summary: already sent today` and sent nothing; and
  with the endpoint pointed at a refused port the cycle exited `0` with one
  WARNING and **no** entry in its problem list - an endpoint having a bad
  afternoon is not a news-radar outage. Contract in [[ai-summary]].
- **A failing cycle now reaches the phone, and it says so exactly twice.**
  Measured in the container on 2026-09-05 against a deliberately 404-ing
  `site_url`, three cycles one minute apart, one process throughout:
  cycle 1 logged `health: 1 consecutive failed cycle(s), alerting at 2` and sent
  nothing; cycle 2 logged
  `alerted 2 of 2 channel(s) [telegram, discord]` carrying the reason; cycle 3
  logged `health: 3 consecutive failed cycle(s)` and sent **nothing**. A separate
  run flipped the site healthy on the third cycle and got one recovery message
  and a ping. Two messages per outage of any length - that is P6-2's definition
  of done.
- **The ping is a claim that the cycle worked, and it is withheld the moment it
  would be false.** `heartbeat: cycle unhealthy, the ping is withheld` fired on
  every failed cycle above, and `heartbeat: pinged` only on the clean one. The
  dead-man's switch is what covers the three failures nothing inside the
  container can report - a killed container, a host that lost power, a daemon
  that never came back. From inside, all three look identical: silence.
- **The site check is what finally notices the tunnel.** The crawl fetches its
  own published page before pinging, so `news.dtbao.org` answering Cloudflare
  `1033` while every other log line says success is now a failed cycle rather
  than a thing you find out about days later. Verified live at 19:41 on
  2026-09-05: `heartbeat: https://news.dtbao.org/ answered`.
- **A refused ping is a warning, never an alert.** A monitor outage means the
  radar is fine and the thing that would have told you so is what broke;
  alerting on that is how you train yourself to ignore the alert.
- **The store has a backup, and it is taken before anything is deleted.**
  Measured 2026-09-05: `backup: wrote backups/news-2026-09-05.db, 0 older
  copy(ies) dropped, 1 kept`, 253952 bytes, and the copy opens as a real store -
  `PRAGMA integrity_check` **ok**, `user_version` 1, 90 items, 618 matches, 14
  runs. The `--once` a minute later correctly wrote nothing: one copy per day,
  not 48.
- **`backups/` is outside the served directory, not merely excluded from it.**
  `output/` is what Caddy roots on, and a dated copy of the whole archive sitting
  there would be one Caddyfile line from being downloadable. The bind mount is on
  the crawl service only; `caddy` has no mount for that path at all.
- **The archive has a ceiling.** The shipped template moves to
  `retention_days: 90`. The *default* for an absent key stays `0`, so upgrading a
  deployment that never mentioned the key cannot make it start deleting rows
  nobody chose to lose.
- **One more stdlib-only test file.** `tests/test_ops.py` needs only
  `http.server`; twelve of the fourteen test files now run on a bare Windows
  checkout, and only `test_feeds` and `test_search` still need `feedparser`.
- **Still two runtime dependencies.** P6 added none - the ping and the site check
  are the `Fetcher` that already existed, and the backup is `sqlite3`.

### P5 - Deploy

- **`https://news.dtbao.org` serves the report.** Measured 2026-09-05 from this
  machine, which leaves the LAN and comes back through the Cloudflare edge:
  `GET /` answered **200** with `<title>news-radar &middot; 2026-09-05</title>`
  and 42914 bytes, `GET /news.db` answered **404**, `GET /days/` answered
  **404**. That is P5's definition of done.
- **The connector runs in the stack, not on the host.** A `cloudflared` service
  in `docker/docker-compose.yml` carries the `news` tunnel and registered four
  edge connections on first start (`hkg01`, `hkg09`, `hkg13` x2). The id was
  written into `docker/cloudflared.yml` at the time; it moved to
  `NEWS_RADAR_TUNNEL_ID` in `.env` later, so no committed file names this
  deployment.
- **The bank had this topology wrong, and it is now corrected.** It said the
  homelab already ran a tunnel *container* for `mcp.dtbao.org` that this project
  would attach to. Reality: cloudflared runs here as a Windows service named
  `win-dev` carrying `ssh.dtbao.org` and `remote.dtbao.org`. A host connector
  cannot resolve `caddy`, so the documented `http://caddy:8080` origin was only
  reachable by putting a connector inside the stack - which also means the news
  route never shares a restart with the operator's own ssh and rdp.
- **The route existed before the connector did.** `news.dtbao.org` was already
  a DNS record pointing at the `news` tunnel, and the tunnel had never been run:
  the site answered Cloudflare error `1033`. Starting the container was the
  whole of P5-3.
- **A tunnel id is not a secret; the credentials file is.**
  `docker/cloudflared.yml` carries the id and the ingress and is committed;
  `docker/tunnel-credentials.json` is gitignored, and `git check-ignore` was run
  to prove it before the first commit.
- **The service is behind the `tunnel` compose profile**, so `docker compose up
  -d` on a fresh clone starts exactly what it started before rather than a
  container crash-looping on a missing bind mount. `scripts/setup.py` adds
  `--profile tunnel` on its own when it sees the credentials file, so installing
  is still two steps on a machine that publishes.
- **One more stdlib-only test file.** `tests/test_setup.py` needs only
  `pathlib` and `tempfile`; eleven of the thirteen test files now run on a bare
  Windows checkout.

### P4 - Notify

- **New stories arrive on the phone, and a quiet cycle is silent.** Measured in
  the container on 2026-09-05: the first `--once` after the rebuild sent
  **2 Telegram messages and 5 Discord messages carrying the same 43 stories**,
  and the `--once` straight after it printed `nothing new to send` on both
  channels and sent nothing. Both halves are P4's definition of done.
- **Five messages on Discord against two on Telegram is arithmetic, not a bug.**
  1900 characters is a quarter of Telegram's 4000, so the same run costs more
  messages there. Both limits sit under the real ones (2000 and 4096) because
  Telegram counts UTF-16 code units and `len()` does not.
- **A story is marked sent only after the message carrying it was accepted**, and
  the seen-set is per channel. A crash between the send and the write re-sends;
  enabling Discord later does not replay everything Telegram already had.
- **A refusal ends that channel for the run, and costs nothing else.** The page
  is already written by then, and the other channel is still attempted - two
  guards, the outer one around the store work and the inner one per channel.
- **`report.mode` finally does something.** It was validated by `config.py` from
  P0 and read by nothing, so `mode: daily` was accepted and silently ignored.
  `incremental` sends this run's new matches, `current` the whole shortlist every
  cycle, `daily` everything today that has not gone out yet.
- **The transport learned to POST and to read `Retry-After`.** Both live in
  `Fetcher`, so the GET path gets the 429 fix too - Google News throttles as
  readily as a bot API. The delay is capped at 60 s: a server asking for fifteen
  minutes would stall a thirty-minute cycle past its own interval.
- **Three sets of dangerous characters, not one.** The page escapes for HTML,
  Telegram for its own HTML subset, Discord for Markdown - and a `[` that is
  harmless in the first two ends a Discord link early. `tests/test_notify.py`
  pins each set, and pins that a story is never split across two messages.
- **One more stdlib-only test file.** `test_notify.py` needs only `http.server`
  and `json`, so ten of the twelve test files now run on a bare Windows
  checkout.
- **Still two runtime dependencies.** Both channels are `urllib` and `json`.

### P3 - Store and render

- **The page exists and history survives a restart.** Measured in the container
  on 2026-09-05: `python -m news_radar --once` wrote `output/news.db` and a
  29 KB `output/index.html` plus `output/days/2026-09-05.html`. A second `--once`
  found the same 50 stories and **all 50 of the first run's stories were still on
  the page** - that is P3's definition of done.
- **The page is rendered from the store, not from the run in memory.** Proven
  rather than asserted: five stories scored higher in run 1 than in run 2, and
  the page carried run 1's score for all five (agreement to within 1e-9). A page
  built from `ranked` could not do that.
- **Five tables, one file, migrated on `user_version`.** `items`,
  `item_sources`, `matches`, `reported`, `runs`. A store written by a *higher*
  schema version raises `StoreError` rather than being downgraded.
- **The sources are a table, not a JSON column.** The union of sources is then an
  `INSERT OR IGNORE` away instead of a read-modify-write on every re-sighting.
  A deliberate departure from the design - see [[news-item]].
- **Three re-sighting rules are pinned by tests.** `first_seen_at` never moves;
  `published_at` keeps the earliest non-null and a `NULL` never overwrites a real
  timestamp; the source set accumulates.
- **The seen-set is per channel.** `unreported()` and `mark_reported()` landed
  here with no caller; P4 is the caller. Marking a story sent on Telegram leaves
  it unreported on Discord.
- **The page is self-contained, and the test asserts it.** No external
  stylesheet, script or image - a report that needs a CDN stops being readable
  exactly when the network is the thing you wanted to read about. Dark mode with
  `localStorage`, a search box that folds diacritics the way the matcher does, a
  link to every past day, and the first `report.rank_threshold` of each group
  highlighted.
- **Every title, link and source id is escaped on the way in.** A feed title is
  somebody else's text arriving unreviewed every thirty minutes; the test pins a
  `<script>` in a title coming back escaped.
- **Storage and rendering cannot cost the fetch.** `_publish()` is wrapped whole;
  a failure is logged with its traceback and the cycle still returns the
  shortlist.
- **Two more stdlib-only test files.** `test_store.py` needs only `sqlite3` and
  `test_render.py` only `html` and `pathlib`, so nine of the eleven test files
  now run on a bare Windows checkout.

### P2 - Filter and rank

- **`python -m news_radar --once` prints a shortlist, not a pile.** Measured in
  the container on 2026-09-05: **597 raw items -> 209 matched -> 205 stories
  after dedup -> 50 kept across 7 groups, exit 0**, in 37 s. That is P2's
  definition of done.
- **The global filter runs before any group sees the item.** `filter.blocked()`
  is called first by `select()`, so a story carrying `giveaway` cannot sneak in
  through a group that happens to match it.
- **Folding works on real Vietnamese titles.** A keyword typed `dien tu` finds
  `Điện tử`; `ESP32-S3` keeps its hyphen through folding, so the part number
  still matches. A `/regex/` runs against the **original** title - proven by a
  check that the lowercased form of a `CVE-2026-1234` title does not match
  `/CVE-\d{4}-\d+/`.
- **Every group is reported, empty ones included.** `Security - 0 item(s)` is a
  line in the run, not a missing section: a keyword that has gone quiet is
  exactly what a total would hide.
- **Layer 3 imports no config and reads no clock.** The weights, the
  `{source_id: rank_weight}` map and `now` are arguments; `__main__` builds
  them. That is why `test_filter.py` and `test_rank.py` run on a bare Python
  with neither PyYAML nor feedparser installed - seven of the nine test files
  now run on the host.
- **Two timestamp rules are pinned by tests, not by hope.** No `published_at`
  gives a freshness term of exactly `0`; a *future* timestamp scores no higher
  than one published now, because `0.5 ** negative` is greater than 1 and one
  bad `pubDate` would otherwise top every group.

### P1 - Fetch

- **`python -m news_radar --once` pulls real news.** Measured in the container
  on 2026-09-05: **597 raw items in 57 s, exit 0** - 208 from the eight fixed
  feeds and 389 from seven keyword groups crossed with two search templates.
  Both kinds of source contribute, which is exactly P1's definition of done.
- **One dead source costs one line, never the run.** `www.reddit.com` does not
  resolve from this homelab (`Name or service not known`, on the host and in the
  container alike - it is DNS, not the 403 the design predicted). The run
  reported it once, printed `r_embedded 0 item(s) [failed]`, and kept the other
  21 sources. `feeds.read_source()` is the single place that guard lives;
  `search.py` reuses it rather than repeating it.
- **Every source is counted by name, zeros included.** A feed that silently
  stops returning items looks identical to a quiet week inside a total, so the
  cycle prints a line per configured source rather than one grand number.
- **Three formats, dispatched on the declared type.** RSS 2.0 and Atom through
  `feedparser`, HN Algolia's JSON by hand - never on the response content type.
  Verified live against `lobste.rs` (25), `hackaday` (7) and Algolia (20),
  including a Show HN post with no outbound url falling back to its permalink.
- **Search queries are exact.** A multi-word primary term is quoted as a phrase
  before encoding (`%22embedded+linux%22`), and the template's own locale
  parameters survive character for character. `build_urls()` is pure, so the
  request count is known before the first byte goes out.
- **Five test files, none of which touch the network.** `test_item`,
  `test_keywords` and `test_http` need only the standard library (the last runs
  a local `http.server` to play a 403, a retryable 500, a gzipped body and a
  handler slow enough to time out); `test_feeds` and `test_search` read
  `tests/fixtures/`, one body per predicted edge case.
- **`keywords.py` landed early.** It is P2-1, written in P1 because the search
  generator needs each group's primary term and finding that correctly already
  means skipping every other prefix. It parses the shipped
  `config/frequency_words.txt` into its 6 groups with the right caps, labels,
  required terms and regexes - including the two AI groups, whose word
  boundaries live in a regex because plain-term matching is substring.

### P0 - Foundation

- **v0.1.0 is published.** `python scripts/release.py 0.1.0` ran the whole chain
  without stopping: promoted the changelog, wrote `VERSION`, committed on
  `release/v0.1`, merged into `developing` then `main`, tagged, returned, pushed
  all three branches and the tag. CI published the GitHub Release from the tag,
  with the `## v0.1.0` changelog section as its notes. Five workflow runs, all
  green. `main` carries real content for the first time.

- **The design bank is complete enough to build from.** Thirteen durable docs
  plus one ADR cover the target architecture, the sources and their exact URLs, the
  item shape and dedup rule, every config key, the keyword-file syntax, the
  notification contracts, the crawl algorithm with its known edge cases, and the
  release and setup procedures.
- **`python scripts/setup.py` works on Windows and Linux.** Verified on this
  machine (Python 3.12, Docker Compose v2): it enforces the Python 3.11+ floor
  and the presence of Compose v2, creates
  `config/config.yaml` and `docker/.env` from their templates without ever
  overwriting an existing file, prompts for missing secrets while preserving the
  `.env` comments, and exits non-zero while a required secret is blank.
  `--dry-run`, `--check`, `--force` and `--non-interactive` all behave as
  documented.
- **`python scripts/release.py <version>` works, end to end.** It no longer
  reads the commit log: the changelog is hand-written into `## Unreleased` and
  the script promotes that section to the version, opening a fresh empty one.
  A missing or empty section fails the preflight - proven by emptying the section
  and watching a real run refuse with exit 1, nothing changed. `--dry-run` prints
  the body it would promote and the exact git chain. `python tests/test_release.py`
  passes with plain asserts and no test framework.
- **CI publishes a release from a tag.** `.github/workflows/release.yml` triggers
  on `v*`, cuts the version's section out of `CHANGELOG.md` using `release.py`'s
  own extractor, and falls back to GitHub-generated notes when there is no
  section. Both paths were exercised locally against the real workflow code.
- **CI runs the checks on every push and pull request.**
  `.github/workflows/test.yml` installs `requirements.txt`, then runs every
  `tests/test_*.py` on Python 3.12 - the loop picks up a new test file without
  the workflow being edited. Verified locally by running the same loop, by proving a
  failing check aborts it instead of passing silently, and by every green run
  since.
- **`setup.py` starts the stack itself, verified end to end.** A successful run
  ends with `docker compose up -d`, not a command printed for the operator to
  copy. Install is two steps, not three. Exercised on this machine on 2026-09-05
  with real credentials in `docker/.env`: exit 0, `[ok] stack is up -
  http://localhost:8088`, and Caddy answering `200` there. The failure paths were
  exercised too - a stopped daemon reports `docker compose exited 1` and returns
  non-zero, and a blank secret stops the run before docker is touched at all.
- **The docker stack is defined and Caddy actually runs.** Verified by starting
  it: Caddy serves `output/` with the `Cache-Control` headers from our Caddyfile.
- **The repository has a license.** Apache-2.0, in `LICENSE`, chosen because
  the clean-room decision left it free (`adr-0001`). The README states it and
  carries a badge.

- **The full stack starts, both services.** `Dockerfile` (base pinned by
  digest), `requirements.txt`, and the `src/news_radar/` skeleton exist, so
  `docker compose up -d` builds and runs the crawl service alongside Caddy.
  Verified on 2026-09-05: `setup.py` widened from `up -d caddy` to `up -d` on its
  own once the Dockerfile appeared, both containers report `Up`, and the crawl
  service logs its cycle then waits.
- **`python -m news_radar` runs.** Loads and validates the config, refuses to
  start when an enabled channel has no secret (verified in the container: three
  problems listed, exit 1), and honours `SIGTERM` mid-interval - `docker stop`
  returned in under a second because the loop waits on an Event rather than
  sleeping. `crawl()` was an honest placeholder at that point; P1 replaced it
  with the real fetch layer.
- **`python tests/test_config.py` passes.** Covers the default merge, the
  fatal-secret rule, and the validation gates, and asserts the committed
  `config.yaml.example` satisfies its own contract.

## What's left

**Time, not code.** Every module the design bank specifies is now written: the
entrypoint, the config loader, the item shape, the keyword parser, the whole
fetch layer, the whole selection layer, the store, the renderer, both senders,
the ops layer and the summary - and the whole thing is reachable at
`https://news.dtbao.org`.

- **Seven days unattended is the one thing still open.** It is P6's definition of
  done, and the clock starts when this branch merges: nothing has yet run
  unattended for longer than a cycle. What to look at on day seven: the crawl
  container still `Up` with no restart, `backups/` holding one file per day and
  no more, the page's day list not older than 90 entries, and however many alerts
  arrived being ones you would have wanted.
- **`ops.heartbeat_url` is still empty**, so nothing outside the stack is
  expecting a ping yet. Until a healthchecks.io or Uptime Kuma url goes into
  `config/config.yaml`, the half of P6-1 that survives the container being killed
  is built but not armed. The site check and the alerting work without it.
- **P6-4, the AI summary, has now run against a real endpoint** (2026-09-07) -
  see [[ai-summary]] for the contract. It still *ships* `ai.enabled: false`;
  what changed is the homelab, which now points at OpenRouter. The open question
  recorded here - whether two sentences a topic reads as a summary or as a
  horoscope - is answered, and the answer is that it reads as a summary. See
  What works.
- **Nobody has yet watched a real outage they did not cause.** Every alert so far
  came from a `site_url` pointed at a 404 on purpose. Whether `ALERT_AFTER = 2` is
  the right chattiness against real feed flakiness is a question only the seven
  days can answer.

## Known issues

- **The OpenRouter key is on the free tier, so the model can 429 at any time.**
  `is_free_tier: true`, no credits, and only `:free` models resolve at all -
  a paid model id would answer `402`. A rate-limited cycle is already the
  designed failure mode (`summarize()` returns `None`, one WARNING, the page is
  written without the block, the cycle still counts as healthy), so nothing
  breaks - but the summary is best-effort until the account has credit.
- **The `RTOS` keyword group is polluted by Indian transport offices.** `RTOS`
  matches `RTOs` after folding, so three of the group's five top stories on
  2026-09-07 were about Regional Transport Offices and e-rickshaw enforcement.
  The AI summary routed around it by omitting the topic; the page does not. The
  fix is a case-sensitive regex in `frequency_words.txt` - a `/RTOS/` term runs
  against the **original** title, not the folded one - but that is a local file
  on the deployment, so it is an operator edit rather than a release.
- **Auto-update has no safety net, and this is the one to weigh before turning
  it on.** A release whose *cycles* fail is reported - `ops.Health` sends one
  message on the second consecutive failure. A release that **will not start**
  is reported by nothing: `main()` returns `1` from the `ConfigError` branch
  (`__main__.py:611`) before `run()` builds `health = ops.Health()` (`:563`), and
  `restart: unless-stopped` gives every restart a fresh counter that never
  reaches two. Measured against a container with an empty config directory: **9
  restarts in 45 seconds, zero `starting` lines, zero health lines** - loud in
  `docker logs`, silent on every channel. The shape that covers it is the
  dead-man's switch, and `ops.heartbeat_url` still ships empty. Arm a monitor
  before `--profile autoupdate`, or accept that a bad release goes unnoticed
  until somebody opens the page.
- **A new GHCR package is private, even from a public repo.** A package
  published by a workflow inherits the repository's access permissions but
  **not** its visibility, so the first `docker compose pull` on the homelab will
  answer `denied` until the package is switched to Public by hand. One-time, and
  a step the migration cannot skip.
- **A wrong `NEWS_RADAR_HOME` leaves root-owned directories behind.** Docker
  creates a bind-mount path that does not exist, as `root`. The container then
  crash-loops on the missing config - which is the loud, easy half - but the
  three empty directories on the host cannot be removed without `sudo`. Found
  while verifying, when the cleanup step of the test itself failed on it.
- **Nothing published to GHCR yet, so nothing can be pulled.** The workflow
  exists and is tested as far as a workflow can be tested without running; the
  first real evidence is the `Publish image` run going green after the next
  `release.py`. Until then `docker compose pull` has nothing to fetch, and the
  homelab migration cannot start. Cut the version first, in that order.
- **v0.2.2 is cut and pushed but not deployed.** The homelab still runs
  `v0.2.1`. The tunnel in front of it is gone as of 2026-09-07, but **its
  compose file still defines the `cloudflared` service** - only the container
  was removed, so `--profile tunnel up -d` there would start it again against a
  tunnel that no longer exists. The compose file without that service arrives
  with the migration.
  `~/news-radar/config/config.yaml` is gitignored and still says
  `report.mode: incremental` - a hand edit no release can make for you, and what
  `--check` will name.
- **The `git checkout` that deletes `config/frequency_words.txt` is now
  avoidable, but only if the migration is followed.** That file stopped being
  tracked after v0.2.2, so `git checkout <tag>` past it deletes the deployment's
  tuned groups. The migration in [[setup-homelab]] never checks anything out -
  it removes `.git` and pulls an image instead - so the trap is stepped around
  rather than walked into. Doing a plain `git checkout v0.2.3` on the homelab
  out of habit still springs it. Read `## Migrating an existing checkout` before
  that visit, not after.
- **This dev checkout's own `config/config.yaml` says `report.mode:
  incremental`** too, found while verifying `--check`. Harmless here (it is
  gitignored and this machine is not production) but it is the same drift, and
  it is what `--check` is for.
- **A day page written before the fix stays broken.** Only today's snapshot is
  rewritten each cycle; a past day keeps whatever nav it was written with. On
  2026-09-06 the homelab held exactly one day file, so this costs nothing now -
  but a page written today and read next month is the shape to remember.
- **The archive is readable by anyone who can reach the port.** Every
  `output/days/*.html` ever written, with no auth anywhere in this stack - only
  `news.db*` and directory listings are withheld, both by the Caddyfile. That
  used to mean "public", because a tunnel carried it to the internet. It now
  means "public to the LAN", and it becomes public again the moment anything is
  put in front of the published port. Worth deciding on *before* that, not
  after.
- **Nothing in the stack carries the report off the LAN any more, and nothing
  monitors whatever does.** The tunnel was removed (2026-09-07). `ops.site_url`
  pointed at `http://caddy:8080/` still checks the thing this stack owns - a
  dead web server withholds the heartbeat ping - but a reverse proxy or tunnel
  someone puts in front of the port is outside that check by design: making
  somebody else's outage into a failed cycle would withhold the ping for a
  problem the crawl cannot fix.
- **Google News (vi) has almost no recent embedded coverage.** P2's
  relevance-first problem is fixed - `when:7d` on Google News and
  `search_by_date` on HN Algolia mean the freshness term finally fires, and ten
  stories now clear the source-only floor of `0.40` where none did. But the
  window has nothing much to select: measured 2026-09-05, seven queries returned
  **16 items instead of 253**, with `ESP32`, `RTOS`, `embedded linux` and
  `Rust embedded` returning **zero** even at `when:30d`. The operator itself
  works - `Samsung` bare returns items aged up to 433 h and `when:7d` caps at
  167.5 h - the Vietnamese index simply has no recent articles on these terms.
  The 237 items lost were three to eight months old, scored exactly `0.40`, and
  were filling whole groups (the `Firmware` group was ten Vietnamese AirPods
  articles). Kept deliberately: fewer and fresh beats bulkier and stale. Getting
  volume *and* freshness would mean an English locale, which is a different
  editorial decision, not a bug fix.

- **The pre-rewrite root commit is still reachable on GitHub.** History was
  rewritten on 2026-09-05 to drop a `Co-Authored-By` trailer, but a force push
  does not delete the old objects: `91ea2d9` still answers over the API with the
  trailer in it, and the repository is public. It clears when GitHub garbage
  collects, which cannot be triggered from here.
- **Every bank doc is now `confirmed`.** `config-and-env` was the last one marked
  `inferred`; P6 checked it key by key against `config.py` and flipped it. The
  check earned its keep: four rows were printing the *template's* value in the
  Default column where the code's default is different - `feeds[]` and
  `search_templates[]` default to `[]` rather than the 8 and 3 the template
  ships, `search_templates[].enabled` defaults to `true` rather than "varies",
  and `search_templates[].rank_weight` to `1.0` rather than `0.8`. A default is
  what an *absent* key falls back to, and reading the template's value as the
  default is how someone later concludes an upgrade inherits a feed list it does
  not. `delivery-phases` and `deployment-homelab` were flipped by P5,
  `notify-channels` by P4; `news-item`, `news-sources`, `news-search`,
  `module-layout`, `crawl-cli`, `fetch-layer`, `selection-layer` and
  `storage-layer` were already `confirmed`, and the bank carries no inline gap
  markers at all.
- **Google News items are redirector links.** They arrive as
  `news.google.com/rss/articles/CBMi...`, so the same story from Google News and
  from Hacker News will not collapse on `canonical_url` in P2. Accepted, of the
  same class as the AMP limit already recorded.
- **The image does not ship `tests/`, so the suite cannot be run with
  `docker compose exec`.** It runs on the host (ten of twelve files) or, for the
  two that need `feedparser`, in a throwaway container with the repo mounted:
  `docker run --rm --entrypoint sh -v <repo>:/repo -w /repo news-radar-news-radar
  -c 'for t in tests/test_*.py; do python "$t"; done'`. CI runs the same loop on
  a checkout, so nothing is untested - it is only awkward locally.

- **Nobody has read a whole cycle's worth of messages yet.** Five Discord
  messages every thirty minutes may turn out to be noise rather than a report,
  and no test can answer that. It is a tuning question for `report.max_per_group`
  or `report.mode`, not a defect.
- **No default-branch policy on GitHub**: the first pushed branch (`main`) is the
  default, so pull requests target `main` rather than `developing`.
