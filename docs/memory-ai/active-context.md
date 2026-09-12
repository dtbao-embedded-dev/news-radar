---
title: Active Context
updated: 2026-09-12
---

# Active Context

> What is being worked on right now. Read first every session; rewrite when the focus shifts. Transient - not a durable fact.

## Current focus

**Four reader complaints, measured against the live store and fixed
(2026-09-12, unreleased after v0.2.9).** The reader said: the news is not from
today, the firmware keywords are wrong, the same story arrives twice, and one
message is a wall of bullets. Reading the 1269 items in the production store
turned each into a number - 121 duplicates (9.6%), 36 of 94 `Firmware` matches
being camera and console firmware, a seven-day window, no `STM32` group at all.
Full numbers in [[progress]].

The four changes: `dedup_key()` keys on the normalised headline instead of the
canonical URL; schema v3 carries the seen-set across that rekey so nothing is
re-sent; `when:1d` plus `rank.max_age_days: 1`; `STM32` and `AI Model Release`
groups with a narrowed `Firmware`; and one message per story on both channels,
3.5 s apart.

**The config half is live on the homelab (2026-09-12 12:52).** Four surgical
edits to the hand-edited `config/config.yaml` - `report.mode: incremental` ->
`daily`, `max_age_days: 14` -> `1`, and `when:7d` -> `when:1d` in both
templates - and `config/frequency_words.txt` replaced whole. Backups are
`config.yaml.bak-20260912` and `frequency_words.txt.bak-20260912`; every other
hand-edited value (`interval_minutes: 30`, `site_url`, the OpenRouter `ai:`
block) is untouched. The first cycle after the restart logged
`search feeds: 740 item(s) from 13 group(s) x 2 template(s)`,
`notifying 2 channel(s) in daily mode`, and no config or keyword error.

`report.mode: daily` is not cosmetic here: with one message per story a
throttled cycle loses its tail, and `incremental` never offers a missed story
again. It is set **before** the code that needs it, which is harmless - v0.2.9
honours the key.

**v0.2.10 is cut and live (2026-09-12 13:00).** All five CI runs green, the
image published, and the homelab pulled it by hand - watchtower's
`WATCHTOWER_POLL_INTERVAL` is 86400, so a release does not reach the deployment
on its own inside a day. `--check` reports the config up to date.

The first cycle on the new image is the end-to-end proof of all four changes:

```
news-radar 0.2.10 starting
search feeds: 741 item(s) from 13 group(s) x 2 template(s)
rekey: 2568 seen-set row(s) carried onto the new dedup key
migrated output/news.db from schema version 2 to 3
stored 82 match row(s); 309 story(ies) across 13 group(s) today
telegram 12 message(s), 12 story(ies)
discord  12 message(s), 12 story(ies)
```

**309 stories in the day and 12 messages** is the migration working: without the
v2->v3 rekey, `daily` mode would have found the whole day unreported under new
keys and pushed all 309, one message each. And 12 messages for 12 stories is the
1:1 shape - 40 s per channel, which is 12 x 3.5 s exactly.

**The AI summary went quiet for nine hours and now recovers on its own
(2026-09-08, unreleased after v0.2.8).** OpenRouter withdrew the free tier of
the pinned `minimax/minimax-m3:free`; `summarize.py` now falls through to the
`:free` models the endpoint publishes, three a cycle at most. Numbers in
[[progress]].

**Shipped and live, same day.** v0.2.9 is cut and the homelab is running it -
`docker compose pull` + `--profile autoupdate up -d`, `--check` clean, and the
first cycle on the new image logged
`summary: 20 of 20 story(ies) answered by inclusionai/ling-3.0-flash-sante:free`
at 10:40. The homelab's two hand-edited values, both in the gitignored
`config/config.yaml`:

- `ai.model` -> `inclusionai/ling-3.0-flash-sante:free`, replacing the withdrawn
  slug. The pin is asked first, so a dead one buys a wasted 404 every cycle.
- `ai.timeout_s` -> `90`. Not for the pin, which needs 14 s, but for the
  fallback: the next candidate down measured 66 s and would be cut off at 60.
  Backup of the previous file is `config/config.yaml.bak-20260908`.

The 40-story backlog drains at `max_per_run: 20` a cycle. It has a ceiling worth
knowing: a story that ages past `rank.max_age_days` leaves the report before it
is ever summarised.

**~~Unrelated, found in the same log and not yet touched:~~ closed 2026-09-12.**
Discord had refused **36 messages in 24 h** with
`400 {"content": ["Must be 2000 or fewer in length."]}` - `notify.chunk()`
decided whether a part fitted before appending the next line. `messages()`
clips every message to the channel budget, so it cannot happen; see
[[progress]], Known issues.

**Topics reshaped to what the user actually reads (2026-09-07, unreleased
after v0.2.7).** `RTOS` out, five model groups in - `Claude`, `ChatGPT`, `GLM`,
`Qwen`, `DeepSeek` - and the `google_news` (hl=vi) template disabled to keep the
cycle at 34 requests. Numbers in [[progress]].

**Next:** cut a release. Then the homelab needs **both** of its gitignored files
edited by hand or none of this reaches production: `config.yaml` for the new
feeds, `rank.max_age_days`, the disabled `genk`/`google_news`, and
`config/frequency_words.txt` for the five model groups plus `GitHub Trending`.
That file is the one the deployment tunes, so it will not merge on its own.

**Report quality, measured rather than argued (2026-09-07, unreleased after
v0.2.7).** Auditing the shipped sources end to end turned up three defects and
all three are fixed: `genk` disabled (0 of 61 entries carry a date, so it could
never place), a config comment corrected, and an absolute age floor added -
`rank.max_age_days`, template 14. Numbers in [[progress]].

**The pattern across this whole session is worth keeping.** Four separate
things looked obviously right and were wrong until measured: blanket excerpt
matching (+42% noise), `arxiv_cs_ai` (ceiling below every group's cut),
`esp_idf_releases` at weight 0.8 (looked broken, was correct), and `r_embedded`
(looked dead, works on the homelab). Every one was settled by running the real
pipeline against live sources, not by reading the code.

**Next:** cut a release, then the homelab needs both of its gitignored files
edited by hand - `config.yaml` for the new feeds and `rank.max_age_days`, and
`config/frequency_words.txt` for the `GitHub Trending` group. Nothing here
reaches production on its own.

**Sources widened for AI, GitHub trending and Espressif (2026-09-07,
unreleased after v0.2.7).** A survey of 44 candidate feeds, each verified with
the project's own `read_source()`, ended in three changes: per-source excerpt
matching (`feeds[].match_excerpt`), five new shipped feeds, and a regex-only
`GitHub Trending` keyword group. Every number behind them is in [[progress]].

**What the survey settled that guesswork would not have.** Blanket excerpt
matching looked obvious and was wrong - 42% more matches, all noise. `arxiv_cs_ai`
looked valuable and could never place a story. `esp_idf_releases` looked broken
at weight 0.8 and was correct. `r_embedded` looked dead from the Windows box and
returns 25 items on the homelab.

**Next:** cut a release, then edit the homelab's own `config.yaml` **and**
`config/frequency_words.txt` by hand - both are gitignored there, so neither the
new feeds nor the new group reach production on their own. Then watch whether
Google News starts throttling: the cycle now makes 34 requests every ten
minutes.

**The page is off and the radar polls three times an hour (2026-09-07,
unreleased after v0.2.6).** Three changes, all on `release/v0.2`:

- `schedule.interval_minutes` was confirmed to live in **both** places - the
  code default `config.py` `DEFAULTS` (30) and the shipped
  `config.yaml.example`. The template now says **10**; the default stays 30, so
  an upgrade that never mentions `schedule` keeps the half-hour it had. What to
  watch is Google News and HN Algolia, the two hosts already known to throttle,
  now asked three times as often.
- New `report.html` key. `false` ships in the template and **deletes** the
  published page on the next cycle - `index.html` and `days/*.html`, never
  `news.db`. Telegram and Discord already carry every story; a frozen page on a
  web server is a second, worse copy of the same day.
- With the page off, `ops.site_url` is no longer checked. Left alone it would
  404 every cycle, withhold the ping and alert after two - a false alarm about
  a radar that is working.

**Next:** the homelab's own `config.yaml` is a separate, gitignored file. The
new values reach it only by hand, then `docker compose up -d`. Until then the
homelab still polls every 30 minutes and still publishes the page.

**Search quality, reviewed against TrendRadar and measured (2026-09-07,
unreleased after v0.2.5).** The search *mechanics* came out clean - every claim
in `config.yaml`'s comments was re-run and held: `when:7d` cuts the oldest hit
from 2167 days to 6, `typoTolerance=false` cuts HN Algolia from 41,630 hits to
246 and turns the top result from an Ask HN thread into an RTOS story, and the
`hl=vi` template still returns 100 hits for the AI group and 0-1 for every
other. One comment overstates: a quoted phrase is honoured by Google News
(25 entries to 6) and is **inert on HN Algolia** (12,841 to 12,404, identical
top four, `advancedSyntax=true` no different).

**Two real defects, both fixed and both unreleased.** A story matching two
groups arrived twice in one Telegram message; `notify.pick()` now sends it once
under the first group that claims it. And the keyword file could not express a
narrow match at all - see [[progress]] for the RTOS case and the wrong fix that
was on file for a day.

**TrendRadar's answer did not transfer directly, which was the useful part.**
Its keyword file allows a regex-only group and carries regex flags, and its
README teaches `\b` as the fix for exactly this class of false positive - but
it has no search step at all, so it never needed a term to build a query URL.
The mandatory-plain-term rule is news-radar's own, and taking the query from
`=> Label` is news-radar's own way out.

**Next:** cut and deploy, then edit `config/frequency_words.txt` on the homelab
by hand - the code change only makes the fix expressible, it does not apply it
to a deployment's own file.

**The tunnel is gone (2026-09-07).** The `cloudflared` service,
`docker/cloudflared.yml`, `NEWS_RADAR_TUNNEL_ID` and the credentials-file
detection in `setup.py` were all removed one commit after the id was finally
parameterised - which is the honest sequence, because parameterising it is what
made it obvious how much machinery a connector was for a project that writes
HTML into a directory. **The report is served on `NEWS_RADAR_HTTP_PORT` and
published nowhere**; what fronts that port is a decision outside this
repository. `--profile tunnel` still parses and is a no-op.

**Three answers to one question.** The package is the **image** - not an app
binary. The stack is three processes and a binary would package one of them,
while breaking this project's own rule that a release may never overwrite a
local config file. Auto-update is then a registry pull, and "user data
somewhere an update cannot reach" is "the deployment has no git".

**Nothing is live and nothing is even pullable yet.** The image has never been
published; the workflow's first real evidence is the run after the next
`release.py`. Cut the version, then migrate the homelab - in that order, since
the migration's first command is `docker compose pull`.

**The upgrade path was the previous work (2026-09-06, after v0.2.2).** Asking how
a version update is handled found a procedure that existed, described a
production this one is not, and promised a check nothing performed. Four
changes, all unreleased on `release/v0.2`: `setup.py --check` now names config
keys the template has and the local file lacks (and fails on a missing
destination file), `store.open_db()` refuses a store between `0` and
`SCHEMA_VERSION` instead of returning it, `config/frequency_words.txt` became a
local file created from a committed `.example`, and `## Updating` in
[[setup-homelab]] was rewritten for the detached-tag production that actually
runs. **That awkward next deploy no longer has to happen**: the migration above
removes `.git` and pulls an image instead of checking a tag out, so the
`config/frequency_words.txt` trap is stepped around rather than walked into.
Typing `git checkout v0.2.3` on the homelab out of habit still springs it.

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

- **Both tunnel loose ends are closed, and v0.2.4 removed the last drift**
  (2026-09-07). The `news.dtbao.org` CNAME is deleted - `cloudflared` has no DNS
  delete, but `~/.cloudflared/cert.pem` carries an `ARGO TUNNEL TOKEN` block
  whose `apiToken` is a zone credential, which is what `tunnel route dns` writes
  with, so one `DELETE /zones/<id>/dns_records/<id>` did it. The hostname does
  not resolve at all now; the zone holds 9 records and none is `news`. **That
  file is a zone-wide DNS-write credential**, worth knowing before it is copied.
  And 0.2.4 was cut so the *released* compose file carries the watchtower fix -
  the homelab's copy is byte-identical to it again (`52656984a84bcd72` both
  sides), which is how the hand-patch stopped being drift.
- **The deployment compose file is only ever fixed by a release.** A `pull`
  updates the image, never the file that runs it. So a hand-patch on the
  deployment is drift until a version carries the same change and the file is
  re-fetched - which is the argument for cutting a patch release over a one-line
  compose fix rather than leaving it edited in place.
- **v0.2.3 is cut, published and deployed** (2026-09-07) - the first release to
  go out as an image, and the first time the whole pipeline ran for real.
  `Release`, `Test` and `Publish image` all green on the tag; the homelab pulled
  it with no login; phase 1 of the migration left `config/config.yaml`,
  `config/frequency_words.txt` and `output/news.db` byte-identical. The message
  line no longer carries the source id - that fix had been sitting unreleased on
  the branch since 2026-09-06, which is the whole reason the deploy happened.
- **`containrrr/watchtower` cannot talk to Docker 29, and only a real run said
  so.** It pins Docker API 1.25; the daemon refuses below 1.40. The container
  crash-looped 8 times on `client version 1.25 is too old` immediately after the
  migration. Replaced with the maintained fork,
  `ghcr.io/nicholas-fedor/watchtower:1.22.0`, which reports API v1.55, takes the
  same `WATCHTOWER_*` variables, and still scans exactly one container. **A
  compose file that parses, renders and passes every YAML assertion can still
  ship an image that cannot start** - `tests/test_deploy.py` now pins the fork
  and the exact tag, which is the most a test file can do about this class of
  bug.
- **A colon count is not a tag check.** The first version of that test asserted
  two colons in the image reference, because `containrrr/watchtower:1.7.1` has
  one and I extrapolated wrongly to a registry host - `ghcr.io` has no port. It
  reads the last path segment now.

- **The AI summary is live on OpenRouter** (2026-09-07), and P6-4's open
  question is answered: two sentences a topic reads as a summary, not a
  horoscope. `minimax/minimax-m3:free` was picked by POSTing today's real
  3085-character prompt to two free models and comparing the Vietnamese -
  `gemma-4-31b:free` answered `429` upstream. First cycle: `summary: 1576
  character(s) over 5 topic(s)`, page block rendered, `sent to 2 of 2
  channel(s)`, heartbeat clean.
- **A new environment variable needs `up -d`, not `restart`.** The plan on file
  said restart, which is correct for `config.yaml` (a bind mount read at process
  start) and wrong for `.env`: Compose bakes environment into a container when
  it creates it, so a restart reuses the old set and the key never arrives. The
  general shape: bind mounts follow the file, `environment:` follows the
  container.
- **The model omitted a topic and was right to.** `RTOS` matched `RTOs` -
  Indian Regional Transport Offices - so three of that group's five stories were
  about e-rickshaw enforcement, and the prompt's "omit an unremarkable topic"
  rule dropped the line. A model routing around a keyword problem is not a fix
  for it; the page still shows the group.
- **And then it was torn down for real, the same day** (2026-09-07). Not just
  removed from the repository: the connector container stopped and removed
  (`news.dtbao.org` `200` -> `502`, LAN copy still `200`, crawl and Caddy
  untouched), the `news` tunnel deleted from the Cloudflare account (three
  unrelated tunnels left alone, `git.dtbao.org` and `photos.dtbao.org` still
  `200`), and `ops.site_url` moved to `http://caddy:8080/` **before the next
  cycle** - it was still the public URL, and one more cycle would have started
  counting toward a real alert about a hostname nobody was serving on purpose.
- **The DNS record is the one piece no CLI can remove.** `cloudflared tunnel
  route` creates records and has no delete; deleting the CNAME is a dashboard or
  API operation. Until it goes, `news.dtbao.org` answers **530** rather than not
  resolving - the record is still there, pointing at a tunnel that is not.
- **Removing a thing from the repository is not removing it from the world.**
  The bank said the tunnel was gone a day before the connector stopped running.
  Worth separating in writing next time: what the code no longer does, and what
  the deployment no longer runs.
- **Then the tunnel was removed outright** (2026-09-07), one commit later.
  `docker/cloudflared.yml` deleted, the `cloudflared` service and the `tunnel`
  profile gone from compose, `NEWS_RADAR_TUNNEL_ID` gone from `.env.example`,
  and `TUNNEL_CREDENTIALS` plus the profile detection gone from `scripts/setup.py`.
  Twelve bank docs and the README followed. The tests now pin the **absence**:
  no `cloudflared` service, no service declaring a `tunnel` profile, no
  `cloudflared.yml` on disk, only `caddy` publishing a port - and in
  `test_setup.py`, that a leftover credentials file changes nothing.
- **Parameterising a thing is a good way to find out you do not want it.** The
  work below made the tunnel id a variable; doing that laid out every piece a
  connector needs - a config file, a credentials file, a profile, an env var, a
  detection rule in `setup.py` - and the next question was why any of it was in
  a project whose job is to write HTML into a directory.
- **`.gitignore` keeps ignoring `docker/tunnel-credentials.json` on purpose.**
  The path is dead, but a machine that still has one of those files must not be
  able to commit it by accident. Removing an ignore for a secret is the one
  direction that has no upside.
- **History was annotated, not rewritten.** P5 delivered a tunnel and that is
  true; `delivery-phases.md` and the P5 entries in this file say so and now also
  say it was undone. The Known issues list is where the *current* state lives,
  and that is what changed.
- **The repository stopped naming one deployment** (2026-09-07). `docker/cloudflared.yml`
  carried this homelab's tunnel id and its hostname, so the two files a second
  deployment would need were welded to the first one. The id is now
  `NEWS_RADAR_TUNNEL_ID` in `.env`, passed as the argument to `run`; the hostname
  is gone entirely, replaced by a single catch-all ingress to `caddy:8080` -
  Cloudflare DNS already knows which hostname reaches this tunnel. Verified with
  cloudflared itself rather than by reading: `tunnel ingress validate` answers
  `OK`, and `tunnel ingress rule <url>` matches rule #0 to `http://caddy:8080`.
  **Breaking for the running deployment** - the migration has to read the id out
  of the old file before replacing it.
- **cloudflared does not expand environment variables inside its own config**,
  which is the whole reason the id could not just become `${...}` in that file.
  Compose *does* expand them in `command:`, so that is where it went. Checked
  before designing around it, not after.
- **`updating-homelab.md` was split out of `setup-homelab.md`** (2026-09-07).
  The latter had hit the bank's 300-line ceiling twice in two days because it was
  covering two concepts - installing, and updating/migrating. `rule/` orders
  shifted: release-flow 1, setup-homelab 2, updating-homelab 3,
  reference-trendradar 4, changelog 5.
- **A committed `.example` is a place a real value sneaks back in.** The first
  version of the `NEWS_RADAR_TUNNEL_ID` comment used this deployment's actual id
  as its example, putting back into git exactly what the change had just taken
  out. It is a placeholder UUID now.
- **Every "what could break" line was then checked, and four of six were wrong**
  (2026-09-06). Corrections landed in two commits across `.gitignore`,
  `docker/.env.example`, `docker/docker-compose.yml`, `CHANGELOG.md`,
  `deployment-homelab.md`, `config-and-env.md`, `setup-homelab.md`,
  `crawl-cli.md`, `progress.md` and this file. What survived: `up -d` before
  `pull` really does fail on the absent Dockerfile. What did not: the wrong
  `NEWS_RADAR_HOME` story, the "P6 alerts within two cycles" story, and the
  "pinning alone loses to the next poll" story.
- **A "what could break" list written from reasoning is a set of hypotheses.**
  This one was 33% accurate, written by someone who had just read all the code.
  Worth remembering the next time such a list is offered as a closing summary:
  it is the beginning of a verification pass, not the end of one.
- **`ops.Health` covers a failing cycle, not a failing process.** It is built
  inside `run()`, so a config the loader refuses exits at `__main__.py:611`
  before it exists, and `restart: unless-stopped` hands every restart a fresh
  counter. Measured: 9 restarts in 45 s, zero health lines, zero messages. This
  is the argument for arming `ops.heartbeat_url` *before* enabling auto-update,
  and it is now step 1 in Next steps rather than step 3.
- **Watchtower follows the tag the container was created from.** Not `:latest`
  in general - so pinning `NEWS_RADAR_VERSION` freezes a deployment on its own,
  and six places had been written saying the opposite.
- **Docker creates a missing bind-mount path, as root.** A typo in
  `NEWS_RADAR_HOME` therefore leaves three root-owned directories the operator
  cannot `rm`. Found because the verification script's own cleanup failed on it.
- **~~A GHCR package is private even from a public repo~~ - withdrawn.** Read
  from a documentation summary, never tested, and wrong here: the first real
  publish pulled from a machine with no docker credentials, and an anonymous
  registry token fetched the manifest `200`. Second time in two days that a
  "finding" turned out to be something I had only read - see
  [[verify-closing-claims]] in spirit.
- **The image and data-layout work landed in seven commits on `release/v0.2`**
  (2026-09-06): `docker/docker-compose.yml` (the four data mounts, the `image:`
  line, the watchtower service and the label), `docker/.env.example`
  (`NEWS_RADAR_HOME`, `NEWS_RADAR_VERSION`, `WATCHTOWER_POLL_INTERVAL`),
  `.github/workflows/image.yml` (new), `src/news_radar/config.py`
  (`TEMPLATE_CANDIDATES`, `template_path()`, `_key_paths()`, `_mapping()`,
  `missing_keys()`), `src/news_radar/__main__.py` (`--check`, `_check_config()`),
  `Dockerfile` (the baked template), `tests/test_deploy.py` (new),
  `tests/test_config.py`, `CHANGELOG.md`, and six bank docs.
- **The default has to be the old behaviour, or the variable is a migration.**
  `${NEWS_RADAR_HOME:-..}` resolves to the repository root when nothing sets it,
  which is exactly where a checkout's `config/`, `output/` and `backups/`
  already are. That is what let this land without moving a single byte on the
  homelab, and it is why the migration's phase 1 leaves the variable unset.
- **The fourth mount is the one that bites.** The plan said "the three bind
  mounts"; caddy's `../output:/srv:ro` is a fourth, on a different service.
  Left behind it would have the crawl publish to one directory and the web
  server serve another - the site 404s while every crawl log line says success.
  Found by writing the test before the edit.
- **A check that passes by checking nothing is worse than no check.** The first
  R8 run reported byte-identical files while `ls` inside the container showed
  empty directories, which would have been a mount that mounted nothing. Proving
  the mount in both directions first - host file visible inside, container write
  visible outside, `:ro` refusing - is what made the result mean anything.
- **`:ro` on a docker socket is not a sandbox**, and the first comment written
  for it claimed it was. A socket is a socket: the flag stops the socket *file*
  being replaced, every API call still goes through, and access is root on the
  host. The real narrowing is `WATCHTOWER_LABEL_ENABLE` plus the profile. Same
  shape as the `rel="noopener"` with no `target="_blank"` this project already
  shipped once - half a pattern reads as the whole one.
- **`bash -s` reads its script from stdin**, so `docker compose exec` inside a
  heredoc'd remote script eats the rest of the script, and redirecting stdin
  kills it outright. Both were hit in one afternoon. Write the script to a file
  on the remote first.
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

1. **Arm `ops.heartbeat_url` *before* anything else here.** It is one line in
   `~/news-radar/config/config.yaml` and it is now the precondition for
   `--profile autoupdate`, not a nice-to-have: a release that fails to start is
   reported by nothing at all (see progress.md, Known issues). Auto-update
   without it means a bad release goes unnoticed until somebody opens the page.
2. ~~**Cut the version, publish the image, migrate the homelab.**~~ **Done
   2026-09-07.** v0.2.3 is cut, `Publish image` went green on its first run, the
   package came out public, and phase 1 of the migration ran with all three data
   files byte-identical. The homelab runs `news-radar 0.2.3` from
   `ghcr.io/dtbao-embedded-dev/news-radar:latest`, watchtower is scheduled, and
   `--check` reports the config up to date.
3. **Migrate the homelab, phase 1 only.** `## Migrating an existing checkout` in
   [[updating-homelab]]: `rm -rf .git .github`, re-fetch the compose file, `pull`,
   then `up -d` with both profiles. **No data moves and `NEWS_RADAR_HOME` stays
   unset** - the compose file is still in `docker/`, so the default `..` is
   already `~/news-radar`. Do **not** `git checkout v0.2.3` out of habit: that
   is the command that deletes `config/frequency_words.txt`. The tunnel teardown
   is **already done** (2026-09-07): the connector container is removed, the
   `news` tunnel is deleted from the Cloudflare account, and `ops.site_url` on
   the homelab is already `http://caddy:8080/`. What phase 1 still adds there is
   `rm -f docker/cloudflared.yml docker/tunnel-credentials.json` and a compose
   file that no longer defines the service at all - until then, `--profile
   tunnel up -d` on that machine would start a connector for a tunnel that no
   longer exists.
4. **Edit `report.mode` on the homelab by hand, in the same visit.**
   `~/news-radar/config/config.yaml` is gitignored and still says `incremental`;
   no release can reach it, which is what
   `docker compose run --rm news-radar --check` will tell you. Set
   `mode: daily`. Expect a small burst on the first cycle after it - every story
   of the current day the channel has not already been told about goes out at
   once.
5. **Then watch one auto-update happen on its own.** Cut a trivial version after
   the migration and leave it: within `WATCHTOWER_POLL_INTERVAL` the crawl
   container should be recreated and `docker compose logs news-radar | head`
   should say the new version. Until that has been seen once, auto-update is
   built and not proven.
6. **Let it run seven days.** That is P6's definition of done and the only thing
   still open. On day seven: the crawl container still `Up` with no restart,
   `backups/` holding one file per day and no more, the day list capped at 90,
   and however many alerts arrived being ones you would have wanted.
7. **Watch whether `ALERT_AFTER = 2` is the right chattiness.** Every alert so
   far came from a `site_url` pointed at a 404 on purpose; real feed flakiness
   has not been through it yet.
8. **Retention will actually delete something for the first time** once the
   store holds anything older than 90 days. A backup is written immediately
   before each prune, so the first one has a copy standing in front of it.
9. **Still worth eyeballing from P4**: whether 5 Discord messages per cycle is
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
- **No auto-update without a dead-man's switch.** `--profile autoupdate` may not
  be turned on while `ops.heartbeat_url` is empty. Auto-update removes the human
  who would have noticed the deploy, and the failure it most plausibly
  introduces - a release that will not start - is the one shape `ops.Health`
  structurally cannot report. Measured, not assumed.
- **A claim about behaviour is a test that has not been run.** The bank already
  said "a doc sentence that describes behaviour is a test that has not been
  written"; the verification pass extended it. Six such sentences were checked
  and four were wrong, so the rule is now: a "what could break" list is written
  as hypotheses and either measured or labelled unmeasured. Never presented as
  findings.
- **The package is the image, and it is not an app.** The stack is three
  processes - crawl, caddy, cloudflared - so a PyInstaller or Tauri binary would
  package one of them and leave you installing the other two. Docker already
  supplies everything "background app" means here: restart on crash, start at
  boot with no login, log rotation, network isolation. And a single binary would
  have to carry `config.yaml` inside it, which breaks the rule directly below
  this one. The user-facing app is the page at `news.dtbao.org`.
- **Production holds no git checkout.** That is the whole mechanism behind "an
  update cannot clean the data": not a rule anyone has to follow, but the
  absence of the command that does the damage. It is why the deployment gets a
  compose file over HTTP rather than a clone.
- **A default must reproduce the old behaviour.** `${NEWS_RADAR_HOME:-..}` is
  `..` when unset, which is where a checkout's data already lives - so
  introducing the variable moved nothing and broke nothing. A variable whose
  default changes behaviour is a migration wearing a variable's clothes.
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
- **Self-hosted, and published nowhere.** The crawl and the site both run on
  the homelab, and the stack's answer for who can read it is one published port.
  There was a Cloudflare Tunnel in here; it was removed on 2026-09-07 because a
  connector is a permanent moving part - its own credentials, its own failure
  mode (`1033` while every log line says success), its own upgrade story - in a
  project whose job is to write HTML into a directory. **Reaching the report
  from outside the LAN is now a decision made in front of the published port,
  and changing it does not touch this repository.** That is the property being
  bought; the cost is that nothing here monitors whatever fronts it.
- **`ops.site_url` points at `http://caddy:8080/`, not at a public name.** It
  resolves over the compose network, so it tests the web server this stack is
  responsible for. A public URL there turns an outage nobody here can fix into a
  failed cycle and a withheld heartbeat ping.
- **Secrets live only in `docker/.env`.** `config.yaml` is committed as a
  template and a leaked copy must be harmless.
