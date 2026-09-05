---
title: Notification Channels - Telegram and Discord
category: interface
purpose: Every public signature of the notify layer, the exact contract with the Telegram Bot API and a Discord webhook, and how a run decides what to send.
status: active
updated: 2026-09-05
source: src/news_radar/notify/__init__.py, src/news_radar/notify/telegram.py, src/news_radar/notify/discord.py, src/news_radar/__main__.py, src/news_radar/fetch/http.py
confidence: confirmed
keywords: telegram, sendMessage, bot token, chat_id, discord, webhook, content, 429, retry_after, Retry-After, rate limit, message format, 4096, 2000, chunk, pick, clip, SendResult, report.mode, incremental, current, daily, seen set
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
row set and the group order all arrive as arguments, which is why
`tests/test_notify.py` exercises both channels against a local `http.server`
with nothing installed and nothing configured.

## `notify/__init__.py` - what both channels share

| Signature | Returns | Notes |
|-----------|---------|-------|
| `pick(rows_by_label, labels, keys=None)` | `[(label, [row])]` | Group order + the seen-set diff. Empty groups dropped |
| `chunk(blocks, limit)` | `[(text, keys)]` | `blocks` is `[(header, [(line, key)])]`. Every text under `limit` |
| `clip(text, limit=TITLE_MAX)` | `str` | Ellipsis when it had to cut |
| `SendResult(sent, failed, keys)` | dataclass | `.stories` is `len(keys)` |

`TITLE_MAX` is `240`: long enough that no real headline is touched, short enough
that one absurd title plus its link cannot on its own overflow the smaller of the
two budgets and cost the story its message.

**`pick()` does the two things that decide what a channel is even shown.**
`labels` is the group order the keyword file fixes - the same order the page
renders in, because a mapping's own order would shuffle the sections between runs
for no reason a reader could follow. `keys` is the seen-set answer: `None` sends
everything (`report.mode: current`), while an **empty set** means everything has
already gone out - not the same thing, and it must send nothing at all.

**`chunk()` splits on a group boundary first and an item boundary second**, and a
single story is never split across two messages: half a headline with no link is
worse than the same story arriving one message later. When a group has to be
split, its header is repeated on every part - the second message is the one most
likely to be read on its own.

**An empty group contributes nothing.** The page prints `Security - 0 item(s)`
because a reader is looking for the keyword that went quiet; a phone should not
buzz to say nothing happened.

## The row a channel is given

The same row `store.day_matches()` and `store.run_matches()` return - see
[[storage-layer]]. A channel reads `dedup_key`, `title`, `url`,
`canonical_url` and `sources`, and ignores the rest.

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
| `build(groups, limit=LIMIT)` | `[(text, keys)]` - pure, no network |
| `send(fetcher, groups, token, chat_id)` | `SendResult` |

Formatting: `<b>label</b>` per group, then
`• <a href="url">title</a> <i>sources</i>` per story.

- **HTML, not Markdown.** Telegram's Markdown refuses a message over any
  unbalanced `*` or `_` in a headline and the whole message is lost; HTML has one
  escaping rule.
- Every title, link and source id goes through `html.escape(..., quote=True)`
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
| `build(groups, limit=LIMIT)` | `[(text, keys)]` - pure, no network |
| `send(fetcher, groups, webhook_url)` | `SendResult` |

Formatting: `**label**` per group, then ``• [title](url) `sources` `` per story.

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
- Sources sit in a code span because a source id may carry an underscore
  (`hn_algolia`, `r_embedded`) that italics would eat.
- 1900 is a quarter of Telegram's budget: **the same run makes more Discord
  messages than Telegram messages**, which is expected rather than a bug.
  Measured on 2026-09-05, 43 stories were 2 Telegram messages and 5 Discord ones.

## Error handling, both channels

| Condition | Behaviour |
|-----------|-----------|
| HTTP 429 | `Fetcher` sleeps the server's own `Retry-After` (header, else the JSON body) and retries, up to `advanced.max_retries`. Capped at `RETRY_AFTER_MAX = 60 s` |
| HTTP 5xx, timeout, network error | Retried with exponential backoff up to `advanced.max_retries` |
| HTTP 4xx other than 429 | Not retried - a bad token, a bad chat id, a revoked webhook or a body the channel could not parse. The response body is logged, because that is where the fixable half of the failure is |
| Any refusal | **The channel stops for this run.** The same answer is coming for chunk two, and hammering a throttled bot is how throttled becomes banned |
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
