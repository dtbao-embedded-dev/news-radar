---
title: Notification Channels - Telegram and Discord
category: interface
purpose: The exact contract news-radar has with the Telegram Bot API and a Discord webhook, including limits and error handling.
status: draft
updated: 2026-09-04
source: conversation
confidence: inferred
keywords: telegram, sendMessage, bot token, chat_id, discord, webhook, embeds, 429, retry_after, rate limit, message format, 4096, 2000
order: 3
---

# Notification Channels - Telegram and Discord

> Two channels, one payload. `notify/` receives the ranked, already-deduplicated
> match list and is the only place that knows what a message looks like.

## What a channel receives

A channel implementation is handed the run's match list grouped by keyword group,
already filtered to what should be sent under `report.mode`. It decides nothing
about *which* stories go out - only how they are rendered and split.

Contract, as text:

```
send(groups: list[Group], run: RunMeta) -> SendResult
Group    = {label: str, items: list[RankedItem]}
RunMeta  = {run_id: str, started_at: datetime, source_count: int, error_count: int}
SendResult = {sent: int, skipped: int, failed: int, retry_after: float | None}
```

An empty `groups` means **send nothing at all** - not an empty message. A quiet
run must be quiet.

## Telegram

| Aspect | Value |
|--------|-------|
| Endpoint | `POST https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/sendMessage` |
| Required env | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Body | JSON: `chat_id`, `text`, `parse_mode: "HTML"`, `disable_web_page_preview: true` |
| Hard limit | 4096 characters per message (UTF-16 code units, not bytes) |
| Rate limit | ~30 messages/second overall, ~20 per minute to one group chat |
| Throttle response | HTTP 429 with `parameters.retry_after` in seconds |

Formatting rules:

- `parse_mode: HTML` with only `<b>`, `<i>`, `<a href>` and `<code>` used. Every
  title is escaped for `&`, `<` and `>` **before** being wrapped in a tag -
  an unescaped `&` in a headline makes the whole message fail with
  `Bad Request: can't parse entities`, and the story is lost.
- Link preview is disabled: one preview per message would bury the list.
- A group longer than the limit is split on a **group boundary first**, then on an
  item boundary. A single item is never split across two messages.

## Discord

| Aspect | Value |
|--------|-------|
| Endpoint | `POST <DISCORD_WEBHOOK_URL>` |
| Required env | `DISCORD_WEBHOOK_URL` |
| Body | JSON: `content`, optionally `embeds` |
| Hard limits | `content` 2000 characters; at most 10 embeds; 6000 characters total across all embeds; embed `description` 4096 |
| Rate limit | Per-webhook bucket; headers `X-RateLimit-Remaining` and `X-RateLimit-Reset-After` |
| Throttle response | HTTP 429 with a JSON body carrying `retry_after` **in seconds as a float** |

Formatting rules:

- Markdown, not HTML. A title is escaped for `*`, `_`, `` ` `` and `~`, and the
  link is written as `[title](url)` so the raw URL never widens the line.
- Default shape is plain `content` with one line per story. Embeds are used only
  when a group needs a coloured header; the 6000-character total is easier to
  overrun than the per-embed limit, so the check is on the sum.
- 2000 characters is a quarter of Telegram's budget: the same run produces more
  Discord messages than Telegram messages, which is expected, not a bug.

## Error handling, both channels

| Condition | Behaviour |
|-----------|-----------|
| HTTP 429 | Sleep the channel's own `retry_after`, then retry the same chunk once. A second 429 gives up for this run and records `failed` |
| HTTP 5xx | Retry with exponential backoff up to `advanced.max_retries` |
| HTTP 4xx other than 429 | Do **not** retry - it is a bad token, a bad chat id, or a malformed body. Log the response body and fail the channel |
| Network timeout | Same as 5xx |
| Channel fails entirely | The run continues; the page is still rendered and the other channel is still attempted |

A story is written to the `reported` table **only after** its chunk was accepted.
A crash between send and write re-sends on the next run - a duplicate is the
acceptable failure, a silently dropped story is not.

`reported` is keyed per channel, so enabling Discord later does not mark stories
already pushed to Telegram as sent - see [[news-item]].
