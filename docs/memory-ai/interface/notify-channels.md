---
title: Notification Channels - Telegram and Discord
category: interface
purpose: Every public signature of the notify layer, the exact contract with the Telegram Bot API and a Discord webhook, and how a run decides what to send.
status: active
updated: 2026-09-12
source: src/news_radar/ops.py, src/news_radar/notify/__init__.py, src/news_radar/notify/telegram.py, src/news_radar/notify/discord.py, src/news_radar/__main__.py, src/news_radar/fetch/http.py
confidence: confirmed
keywords: alert, Health, ALERT_AFTER, stamp, TIME_FMT, NO_TIME, published_at, timestamp, telegram, sendMessage, bot token, chat_id, discord, webhook, content, 429, retry_after, Retry-After, rate limit, NOTIFY_INTERVAL_MS, one message per story, message format, 4096, 2000, messages, pick, clip, SendResult, report.mode, incremental, current, daily, seen set
order: 3
---

# Notification Channels - Telegram and Discord

> Two channels, one payload. `notify/` receives rows the store already selected
> and is the only place that knows what a message looks like. It decides nothing
> about *which* stories go out - `__main__._notify()` does that, and hands the
> answer down.

## The layer

`notify/` is layer 5 beside `render.py`, and it imports **layer 1** as well as
layer 4: a POST needs the same User-Agent, timeout, retry and per-host gap a GET
does, and honouring a 429's `Retry-After` is a transport concern rather than a
per-channel one. The alternative was a second HTTP client inside `notify/`.

Neither channel reads the environment, the config or the clock. The secrets, the
row set, the group order and the display timezone all arrive as arguments, which
is why `tests/test_notify.py` exercises both channels against a local `http.server`
with nothing installed and nothing configured.

## `notify/__init__.py` - what both channels share

| Signature | Returns | Notes |
|-----------|---------|-------|
| `pick(rows_by_label, labels, keys=None)` | `[(label, [row])]` | Group order, the seen-set diff, and one appearance per story. Empty groups dropped |
| `messages(blocks, limit)` | `[(text, keys)]` | `blocks` is `[(header, [(line, key)])]`. **One message per story**, header included, each text under `limit` |
| `clip(text, limit=TITLE_MAX)` | `str` | Ellipsis when it had to cut |
| `stamp(moment, tz)` | `str` | `published_at` as `TIME_FMT` (`%H:%M %d/%m`), or `NO_TIME` (`--`) |
| `SendResult(sent, failed, keys)` | dataclass | `.stories` is `len(keys)` |
| `NOTIFY_INTERVAL_MS` | `3500` | The gap between two sends, used by `__main__._notify()` |

`TITLE_MAX` is `240`: long enough that no real headline is touched, short enough
that one absurd title plus its link cannot on its own overflow the smaller of the
two budgets and cost the story its message.

**`pick()` does the three things that decide what a channel is even shown.**
`labels` is the group order the keyword file fixes - the same order the page
renders in, because a mapping's own order would shuffle the sections between runs
for no reason a reader could follow. `keys` is the seen-set answer: `None` sends
everything (`report.mode: current`), while an **empty set** means everything has
already gone out - not the same thing, and it must send nothing at all.

**And a story goes out once, under the first group in `labels` that claims it.**
The store is right to hold a row per (story, group) - see [[storage-layer]] -
but a message is read top to bottom once, so the second copy is the reader
scrolling past their own report. Reported from a real Telegram message on
2026-09-07: one Nvidia/Hugging Face story matched both `AI` and `AI Repos` and
arrived twice, identical headline, link, AI sentence and timestamp. Which group
wins is the operator's call, made by ordering `frequency_words.txt`; there is no
score tiebreak to reason about. The dedup runs **after** the seen-set diff, so a
story the diff already excluded never consumes the slot its duplicate would use.

**This is the one place a message deliberately diverges from the page.** The
page is browsed by topic, so a story belonging to two topics still appears in
both of its sections and both counts; only the message collapses it. Marking
follows the message: the key enters `reported` once, so the copy dropped here is
not owed a message next cycle either.

**`messages()` sends one story per message.** A group used to travel as one
message with a bullet per story, split only when it outgrew the channel's
budget. Now each story is its own message and the group name is the heading of
every one of them - a phone shows one story at a glance rather than a wall of
ten, and a reply, a forward or a reaction is about that story. The header is
repeated rather than sent once because every message is now read on its own. 🟢

**A story too long for the channel is clipped, never split.** Half a headline
with no link is worse than a shortened one, and `clip()` has already capped the
title - what can still overrun is an AI sentence, and losing its tail costs
nothing the link does not carry. 🟢

**The rate limit is the cost of the shape, and two things pay it.** A busy cycle
posts twenty messages in a row, and Telegram allows about 20 a minute to one
group before answering 429 - at which point `send()` gives up on the channel for
the whole cycle. `__main__._notify()` therefore builds its **own** Fetcher at
`NOTIFY_INTERVAL_MS` (3500 ms) rather than reusing the crawl's, whose
`advanced.request_interval_ms` of 2 s is a number chosen for reading feeds;
Discord's webhook budget (5 requests per 5 s) is comfortable at the same gap.
The second is `report.mode: daily`, which re-offers whatever a refused cycle
could not deliver - under `incremental` the tail of a throttled run is never
offered again. 🟢

**An empty group contributes nothing.** The page prints `Security - 0 item(s)`
because a reader is looking for the keyword that went quiet; a phone should not
buzz to say nothing happened.

## The row a channel is given

The same row `store.day_matches()` and `store.run_matches()` return - see
[[storage-layer]]. A channel reads `dedup_key`, `title`, `url`,
`canonical_url`, `published_at` and `ai_summary`, and ignores the rest -
`sources` included, since v0.2.2.

**A message line is the page's line.** The page shows a title, the AI sentence
when there is one, and a local time ([[news-item]]); a message that shows the
same story with a source id and no time is a second report, not the same one. `notify.stamp(moment,
tz)` renders `published_at` as `%H:%M %d/%m`, or `--` when the source gave no
timestamp - the page's own honest dash. The format is duplicated from
`render._when()` rather than imported: `render` and `notify` are the two halves
of layer 5 and neither owns the other. `tests/test_notify.py` asserts the two
spellings agree, so the duplication cannot drift quietly.

**The zone is an argument, never the host's.** `__main__._notify()` resolves
`app.timezone` once and hands the same `tz` to `_rows_to_send()` and to every
channel, so a message cannot read an hour off the page it mirrors. `build()` and
`send()` default it to UTC, which is what keeps them callable with no config at
all.

## Telegram

| Aspect | Value |
|--------|-------|
| Endpoint | `POST https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/sendMessage` |
| Required env | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Body | JSON: `chat_id`, `text`, `parse_mode: "HTML"`, `disable_web_page_preview: true` |
| Hard limit | 4096 characters (UTF-16 code units, not bytes) |
| `LIMIT` used | `4000` |
| Throttle response | HTTP 429, `Retry-After` header and `parameters.retry_after` |

| Signature | Returns |
|-----------|---------|
| `build(groups, tz=UTC, limit=LIMIT)` | `[(text, keys)]` - pure, no network |
| `send(fetcher, groups, token, chat_id, tz=UTC)` | `SendResult` |
| `alert(fetcher, text, token, chat_id)` | `bool` - one operational message, **no `parse_mode`** |

Formatting: `<b>label</b>` per group, then
`• <a href="url">title</a>` ⏎ `<i>“gist”</i>` ⏎ `<i>HH:MM dd/mm</i>` per
story **when it has a summary**, and the one-line
`• <a href="url">title</a> <i>HH:MM dd/mm</i>` when it does not - which is every
story under the shipped `ai.enabled: false`.

- **HTML, not Markdown.** Telegram's Markdown refuses a message over any
  unbalanced `*` or `_` in a headline and the whole message is lost; HTML has one
  escaping rule.
- Every title, link and timestamp goes through `html.escape(..., quote=True)`
  **before** being wrapped in a tag. An unescaped `&` makes the message fail with
  `Bad Request: can't parse entities` and every story in it disappears.
- Link preview is off: one preview per message would bury the list under a single
  story's thumbnail.
- `LIMIT` is `4000` rather than `4096` because Telegram counts UTF-16 code units
  and `len()` does not - an emoji in a headline is one Python character and two of
  Telegram's. The headroom is cheaper than carrying a UTF-16 counter.
- `API` is a module-level string so a test can point it at a local server.

## Discord

| Aspect | Value |
|--------|-------|
| Endpoint | `POST <DISCORD_WEBHOOK_URL>` |
| Required env | `DISCORD_WEBHOOK_URL` |
| Body | JSON: `content` |
| Hard limit | `content` 2000 characters |
| `LIMIT` used | `1900` |
| Success | **204 with no body**, not 200 with JSON |
| Throttle response | HTTP 429, `retry_after` at the top level of the JSON body |

| Signature | Returns |
|-----------|---------|
| `build(groups, tz=UTC, limit=LIMIT)` | `[(text, keys)]` - pure, no network |
| `send(fetcher, groups, webhook_url, tz=UTC)` | `SendResult` |
| `alert(fetcher, text, webhook_url)` | `bool` - one operational message, Markdown-escaped |

Formatting: `**label**` per group, then ``• [title](url)`` ⏎ `-# “gist”` ⏎
``` `HH:MM dd/mm` ``` per story **when it has a summary**, and the one-line
``• [title](url) `HH:MM dd/mm` `` when it does not. `-#` is Discord's subtext
and only works at the start of a line.

- **Plain `content`, no embeds.** The 6000-character total across embeds is
  easier to overrun than any per-embed limit, and it buys nothing here.
- A title is escaped for `\` `` ` `` `*` `_` `~` `|` `[` `]`. The brackets matter
  as much as the formatting: a `[` in a headline ends the masked link early and
  leaves a raw URL in the middle of the sentence.
- `(` and `)` are encoded in the **url** half instead, by `_url()` - a closing
  paren there would end the link early.
- A **masked** link rather than a bare url, on two counts: the raw address would
  widen every line past a phone's width, and Discord does not auto-embed a masked
  link, so ten stories stay ten lines instead of ten preview cards.
- The timestamp sits in a code span, where the source ids used to be: it is
  monospaced, so a column of them lines up the way the page's tabular figures do.
  Nothing inside a code span is Markdown-escaped - a backslash there would be
  printed rather than obeyed.
- 1900 is a quarter of Telegram's budget: **the same run makes more Discord
  messages than Telegram messages**, which is expected rather than a bug.
  Measured on 2026-09-05, 43 stories were 2 Telegram messages and 5 Discord ones.

## Error handling, both channels

| Condition | Behaviour |
|-----------|-----------|
| HTTP 429 | `Fetcher` sleeps the server's own `Retry-After` (header, else the JSON body) and retries, up to `advanced.max_retries`. Capped at `RETRY_AFTER_MAX = 60 s` |
| HTTP 5xx, timeout, network error | Retried with exponential backoff up to `advanced.max_retries` |
| HTTP 4xx other than 429 | Not retried - a bad token, a bad chat id, a revoked webhook or a body the channel could not parse. The response body is logged, because that is where the fixable half of the failure is |
| Any refusal | **The channel stops for this run.** The same answer is coming for the next story, and hammering a throttled bot is how throttled becomes banned. One message per story makes this cost the tail of the run, which is what `NOTIFY_INTERVAL_MS` and `report.mode: daily` exist to answer |
| Channel fails entirely | The run continues: the page is already written, and the other channel is still attempted |

Whatever was accepted **before** a refusal still counts as sent, so those stories
are not pushed again tomorrow.

`retry_after` is read off the `Retry-After` header first and the JSON body second,
because the two channels disagree: Telegram nests it under
`parameters.retry_after`, Discord puts it at the top level as a float, and neither
guarantees the header alongside it. An unparseable value (`Retry-After` may also
be an HTTP-date) falls back to the exponential delay rather than earning a date
parser.

## What `__main__._notify()` wires

`enabled_channels()` → `open_db` → `_rows_to_send()` → per channel:
`unreported()` → `pick()` → `send()` → `mark_reported()`.

**Two levels of guard, both in the contract.** The outer one keeps a locked store
or an unreadable run from costing the page, which is already written by the time
this runs. The inner one is per channel: a dead webhook must leave the *other*
channel still attempted, so it cannot be allowed to unwind the loop.

### `report.mode`

| Mode | Rows read | Diffed against the seen-set |
|------|-----------|-----------------------------|
| `incremental` (default) | `run_matches(run_id)` | yes |
| `current` | `run_matches(run_id)` | **no** - re-sends the shortlist every cycle |
| `daily` | `day_matches(day bounds)` | yes - picks up anything today that never went out |

Both read the **store**, never the `ranked` mapping still in memory, so the story
that goes out is the same row, with the same score and the same source list, as
the one on the page.

### The seen-set rule

A story is written to `reported` **only after** the message carrying it was
accepted. A crash between the send and the write re-sends on the next run - a
duplicate is the acceptable failure, a silently dropped story is not.

`reported` is keyed per channel, so enabling Discord later does not count stories
already pushed to Telegram as sent - see [[news-item]] and [[storage-layer]].

## Departures from the original design

Recorded rather than quietly dropped:

- **`send()` takes no `RunMeta`.** The draft passed a run summary so a message
  could carry `run_id`, source and error counts. Nothing consumed it - the page
  already carries that footer - so the parameter was not built.
- **The secrets are read in `__main__`, not in `notify/`.** The draft had each
  channel read its own environment. Passing them in is what lets both channels be
  exercised with no environment at all.

## `alert()` - the operational message, and why it is not a `send()`

P6-2 pushes *failures* down the same two channels the stories use, and the
payload has nothing in common with a story but the transport. `alert()` takes one
string, posts it once, and answers `True`/`False` rather than a `SendResult`:
there is no seen-set to diff, no group order to preserve, nothing to split (an
alert that overran a channel limit would be a bug in `ops.Health`, not a case to
split), and nothing to mark as reported.

**The two channels escape it differently, and neither reuses its own `send()`
rule.** Telegram is posted with **no `parse_mode` at all** - `send()` needs HTML
because a story is a link, but an alert is a sentence, and HTML mode's only
contribution here would be a way for a stray `<` in an exception message to cost
the whole message. The one message you must not lose is the one saying something
is broken. Discord *is* escaped, because it renders Markdown in plain `content`
whether asked to or not, and an exception carrying `*` or `_` would arrive
reformatted or half-eaten.

**When it fires** is decided entirely by `ops.Health` and never here:
`ALERT_AFTER = 2` consecutive failed cycles send one message naming the reasons,
and the first clean cycle after sends one saying it recovered. Two messages for
an outage of any length. `__main__._alert()` guards each channel separately, for
a harder reason than `_notify()` has: it runs *because* something already went
wrong, which makes it the least surprising place in the program for a second
thing to go wrong, and nothing it does may end the schedule loop.
