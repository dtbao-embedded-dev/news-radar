---
title: Config Keys, Keyword File and Environment
category: interface
purpose: Every key in config.yaml, the frequency_words.txt syntax, and every environment variable news-radar reads.
status: active
updated: 2026-09-05
source: src/news_radar/config.py, config/config.yaml.example, config/frequency_words.txt, src/news_radar/summarize.py
confidence: confirmed
keywords: config.yaml, ops, heartbeat_url, site_url, backup_dir, backup_keep, retention_days, ai, ai.enabled, ai.api_url, ai.model, max_per_topic, notify_at_hour, OPENAI_API_KEY, frequency_words.txt, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DISCORD_WEBHOOK_URL, TZ, NEWS_RADAR_CONFIG, schedule.interval_minutes, rank weights, GLOBAL_FILTER
order: 1
---

# Config Keys, Keyword File and Environment

> `config.yaml` holds behaviour and is safe to commit as a template.
> `frequency_words.txt` holds what to hunt for. The environment holds every
> secret, and nothing else.

## config.yaml

Loaded from `NEWS_RADAR_CONFIG`, default `config/config.yaml`. Any key omitted
falls back to the default below.

**The Default column is `config.py`'s `DEFAULTS`, not what the template ships**,
and the two disagree on purpose in four places (marked inline). A default is what
an *absent* key falls back to, so it has to be the harmless value: an upgrade
that never mentioned `storage.retention_days` must not start deleting rows, and a
clone with no `feeds` should fail the "nothing to hunt" gate rather than silently
inherit somebody's feed list. The template is free to be opinionated because
someone chose it.

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `app.timezone` | str | `Asia/Ho_Chi_Minh` | Timezone used when rendering timestamps; storage stays UTC |
| `schedule.interval_minutes` | int | `30` | Sleep between crawls in the in-process loop |
| `schedule.run_on_start` | bool | `true` | Crawl immediately on container start instead of waiting one interval |
| `feeds[]` | list | `[]` *(template ships 8)* | Fixed feeds - see [[news-sources]] |
| `feeds[].id` | str | - | Stable id; used in `sources`, in the report, and as the `reported` key |
| `feeds[].name` | str | - | Display name on the page |
| `feeds[].url` | str | - | Feed URL |
| `feeds[].enabled` | bool | `true` | Skip without deleting the entry |
| `feeds[].rank_weight` | float | `1.0` | Per-source multiplier in the source term of the score |
| `search_templates[]` | list | `[]` *(template ships 3)* | Keyword-driven searches - see [[news-sources]] |
| `search_templates[].id` | str | - | Stable id |
| `search_templates[].url` | str | - | Must contain `{kw}`; the only substitution performed |
| `search_templates[].format` | str | `rss` | `rss`, `atom`, or `hn_algolia_json` |
| `search_templates[].enabled` | bool | `true` | `reddit_search` ships **disabled** in the template - it duplicates the fixed Reddit feed heavily |
| `search_templates[].rank_weight` | float | `1.0` *(template ships `0.8`)* | Search hits rank below front-page hits in the shipped template |
| `keywords.file` | str | `config/frequency_words.txt` | Path to the keyword file |
| `report.mode` | str | `incremental` | `incremental` (only new), `current` (this run's matches), `daily` (whole day) |
| `report.max_per_group` | int | `0` | Global cap per group, `0` = unlimited; a group's own `@n` overrides it |
| `report.rank_threshold` | int | `5` | The first N of each group are highlighted on the page |
| `rank.weight_source` | float | `0.5` | Weight of the source term |
| `rank.weight_frequency` | float | `0.3` | Weight of the cross-source frequency term |
| `rank.weight_freshness` | float | `0.2` | Weight of the freshness term |
| `rank.freshness_half_life_hours` | float | `12` | Age at which the freshness term halves |
| `storage.data_dir` | str | `output` | Where `news.db`, `index.html` and `days/` live |
| `storage.retention_days` | int | `0` **(template ships `90`)** | `0` = keep everything; otherwise prune rows and day files past the window. The default and the template disagree on purpose - an absent key must never make an upgrade start deleting, while a fresh install should have a ceiling |
| `ops.heartbeat_url` | str | `""` | Dead-man's switch pinged after every clean cycle (healthchecks.io / Uptime Kuma push). `""` = no ping |
| `ops.site_url` | str | `""` | GET immediately before the ping; a non-200 withholds the ping and counts as a failed cycle. This is what notices the tunnel connector going away. `""` = no check |
| `ops.backup_dir` | str | `backups` | Where the daily store backup is written. **Never under `storage.data_dir`** - that directory is served to the public web |
| `ops.backup_keep` | int | `7` | Newest N backups kept; `0` = back nothing up |
| `ai.enabled` | bool | `false` | The AI summary. Off is the shipped case: a config that says nothing about `ai` never reaches the network and never sees a bill |
| `ai.api_url` | str | `https://api.openai.com/v1/chat/completions` | Any endpoint speaking the OpenAI chat-completions wire format - OpenRouter, DeepSeek, Groq, a local Ollama. Must be an http(s) url, and non-empty when `ai.enabled` |
| `ai.model` | str | `gpt-4o-mini` | Model id, passed through verbatim |
| `ai.max_per_topic` | int | `5` | Top-scored stories per keyword group that reach the prompt. Must be >= 1: zero is a prompt with nothing in it and a bill for asking |
| `ai.timeout_s` | int | `60` | Per-request timeout for the completion only. `advanced.request_timeout_s` stays the feeds' budget; fifteen seconds would time out every summary while looking like an outage |
| `ai.notify_at_hour` | int | `8` | Local hour (0-23) at or after which the once-a-day summary message goes out. The page is rewritten every cycle regardless |
| `notification.enabled` | bool | `true` | Master switch; `false` renders the page and sends nothing |
| `notification.channels.telegram.enabled` | bool | `true` | Needs `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` |
| `notification.channels.discord.enabled` | bool | `true` | Needs `DISCORD_WEBHOOK_URL` |
| `advanced.request_interval_ms` | int | `2000` | Minimum gap between two requests **to the same host** |
| `advanced.request_timeout_s` | int | `15` | Per-request timeout; nothing outside the process will kill a hung run |
| `advanced.max_retries` | int | `2` | Retries per request, exponential backoff |
| `advanced.user_agent` | str | `news-radar/{version} (+https://news.dtbao.org)` | `{version}` is substituted from `VERSION`; an anonymous UA gets 403 from Reddit |
| `advanced.debug` | bool | `false` | Verbose per-source logging |

**No secret ever appears in this file.** A leaked `config.yaml` must be harmless.

## frequency_words.txt

Plain text, UTF-8. **A blank line separates one group from the next**, and each
group is counted, capped and displayed independently.

| Line form | Meaning |
|-----------|---------|
| `word` | Match if the title contains this term (case- and diacritic-insensitive) |
| `+word` | **Required**: the title must contain this as well, on top of matching the group |
| `!word` | **Excluded**: a title containing this never matches the group |
| `@n` | Cap this group at `n` items after ranking |
| `/pattern/` | Match by regular expression instead of substring |
| `=> Label` | Display name for the group on the page and in messages |
| `# comment` | Ignored |

The **first plain term** of a group is the group's *primary term*: it is what gets
substituted into the search templates. Later plain terms widen the local match but
generate no extra requests.

A group named `[GLOBAL_FILTER]` is special: its `!` lines are applied to every
item from every source before grouping, and it produces no output section.

Worked shape:

```
# hunt embedded firmware stories, at most 10 per run
ESP32
ESP-IDF
+firmware
!tuyen dung
@10
=> Embedded

[GLOBAL_FILTER]
!coupon
!giveaway
```

Here `ESP32` is the primary term - the search templates are queried with it - while
`ESP-IDF` only widens local matching. `+firmware` narrows both.

## Environment variables

The only place secrets live. In the container they come from `docker/.env`;
outside it, from the real environment.

| Variable | Required | Default | Read by |
|----------|----------|---------|---------|
| `TELEGRAM_BOT_TOKEN` | when Telegram is enabled | - | `notify/telegram.py` |
| `TELEGRAM_CHAT_ID` | when Telegram is enabled | - | `notify/telegram.py` |
| `DISCORD_WEBHOOK_URL` | when Discord is enabled | - | `notify/discord.py` |
| `OPENAI_API_KEY` | when `ai.enabled` is true | - | `__main__.py`, handed to `summarize.summarize()`. Asked for even by a local Ollama, which ignores the value |
| `NEWS_RADAR_CONFIG` | no | `config/config.yaml` | `config.py` |
| `TZ` | no | `Asia/Ho_Chi_Minh` | container clock; `app.timezone` still wins for rendering |

Startup validation: a channel that is `enabled: true` with its variable missing is
a **fatal config error**, not a warning - and `ai.enabled: true` with no
`OPENAI_API_KEY` is the same rule applied to a third thing. Silently not sending is the failure mode
this project most wants to avoid. `scripts/setup.py` checks the same rule before
the container is ever started - see [[cli-scripts]].
