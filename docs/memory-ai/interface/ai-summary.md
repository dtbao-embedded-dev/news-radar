---
title: The AI Summary - summarize.py
category: interface
purpose: Every public signature of the AI summary layer, the OpenAI-compatible contract it speaks, and the rules that keep an optional feature from ever costing a cycle.
status: active
updated: 2026-09-05
source: src/news_radar/summarize.py, src/news_radar/__main__.py, src/news_radar/render.py, src/news_radar/fetch/http.py
confidence: confirmed
keywords: summarize, build_prompt, daily_key, SENTENCES_MAX, ai.enabled, ai.api_url, ai.model, max_per_topic, notify_at_hour, OPENAI_API_KEY, chat completions, OpenAI-compatible, Ollama, per-topic summary, P6-4
order: 8
---

# The AI Summary - `summarize.py`

> One line per keyword group, in Vietnamese, from any endpoint speaking the
> OpenAI chat-completions wire format. Off by default, and constitutionally
> unable to fail a cycle.

## Signatures

```
SENTENCES_MAX = 2

daily_key(local_date)                                  -> str
build_prompt(rows_by_label, labels, max_per_topic)     -> str
summarize(fetcher, api_url, api_key, model,
          rows_by_label, labels, max_per_topic)        -> str | None
```

`rows_by_label` is the shape `store.day_matches()` returns; `labels` is the
keyword file's group order, the same list the page renders in.

Layer 5, importing **layer 1** only - the same widening `notify/*` and `ops.py`
already take. No config, no clock, no store: everything arrives as an argument,
which is why `tests/test_summarize.py` exercises every path against a local
`http.server` with nothing installed. See [[module-layout]].

## No third dependency

P6-4 was dropped once partly for needing an `openai` package against the
two-dependency rule. It ships instead as one `Fetcher.post_json()` with an
`Authorization: Bearer` header - see [[fetch-layer]] for why that header is
merged *underneath* the transport's own. The **wire format** is what is named,
not the vendor: OpenRouter, DeepSeek, Groq and a local Ollama all answer
`/v1/chat/completions`, and the last has no bill. Full reasoning in
[[delivery-phases]].

## The request

| Field | Value |
|-------|-------|
| Method | `POST` to `ai.api_url` |
| Header | `Authorization: Bearer $OPENAI_API_KEY`, **omitted entirely when the key is unset or blank** |
| Body | `{"model": ai.model, "messages": [{"role": "user", "content": <prompt>}], "temperature": 0.3}` |
| Read back | `choices[0].message.content`, stripped |
| Timeout | `ai.timeout_s` (default 60) - a dedicated `Fetcher`, because `advanced.request_timeout_s` is the feeds' 15 s |

`temperature` is low but not zero: a summary read every day should not be the
same four sentences with the nouns swapped, and nothing here needs
reproducibility.

## A key is optional

An SGLang, vLLM or Ollama on the LAN authenticates nobody, so an empty
`OPENAI_API_KEY` sends **no `Authorization` header at all** rather than
`Bearer ` - which is at best ignored and at worst a 401 from whatever sits in
front of the endpoint. `config.py` matches: `ai.enabled: true` with no key
starts fine, and only `ai.api_url` is required. That parts company with the
notification channels on purpose - a channel genuinely cannot work without its
secret, while refusing to start here would be the config file telling the
operator their own server does not exist. The visibility the fatal check was
protecting survives anyway: a hosted endpoint with no key answers 401, logged at
WARNING every cycle.

## The prompt is per topic, and a quiet topic is not in it

`build_prompt()` walks `labels` in order, takes the first `max_per_topic` rows
of each group - already `score DESC` from `store._matches()`, so "the notable
ones" is a slice and not a second ranking pass - and emits one block per topic.
**A group with no rows contributes no block**, so the model is never handed a
topic it would have to fill with "nothing today".

The instruction is written in English (everything in this repository is) and
asks for a Vietnamese answer in one shape:

```
<topic name> — <at most SENTENCES_MAX sentences>
```

No links, no numbering, no heading, no preamble, and a topic whose stories are
unremarkable omitted entirely. That bound is the whole reason the daily message
stays a glance rather than a wall of text.

`build_prompt()` is pure - no clock, no network, no config - and returns `""`
when nothing is notable, which short-circuits `summarize()` before any request.

## One failure mode: `None`

`summarize()` never raises. Each of these is a page without a paragraph and a
message that does not go out:

| Cause | Handling |
|-------|----------|
| Empty `api_url` | Returns before any request |
| No story in any group | Returns before any request; logs at INFO |
| `HttpError` - refused, timed out, 4xx, 5xx | WARNING, `None` |
| A 200 that is not JSON (a proxy's HTML error page) | WARNING, `None` |
| A body missing `choices` / `message` / `content` | WARNING, `None` - every provider claims this shape and one will be wrong |
| An empty summary | WARNING, `None` |

**And the caller adds nothing to `problems`.** An endpoint having a bad
afternoon is not a news-radar outage: it must never withhold the heartbeat ping
or trip an ops alert. The optional thing may not speak for the thing that is
not - the mirror of the asymmetry in [[delivery-phases]] where a refused ping is
a warning and a dead site is a problem.

## Page every cycle, phone once a local day

`__main__._summarize()` runs inside `_publish()`, on the same `day` rows the page
renders, so the paragraph at the top describes exactly what is under it.
`_publish()` returns `(run_id, summary)`.

`__main__._send_summary()` then pushes it - **before `_notify()`, not after**. A cycle can push dozens of story messages, and a summary sent behind them is one nobody scrolls back up to find: observed on 2026-09-05, when a keyword change made 43 stories newly unsent and buried the day's summary under eighteen messages of links. It holds back two ways:

- **Before `ai.notify_at_hour` local**, it logs `summary: holding until HH:00
  local` and sends nothing.
- **Once a day, per channel.** `daily_key(local_date)` -> `"summary:<ISO date>"`
  rides in the existing `reported` table via `store.unreported()` /
  `store.mark_reported()`, so "already sent today" survives a container restart
  - the same mechanism that keeps a story from being sent twice. The `summary:`
  prefix is what keeps it from colliding with a dedup key, and `store.prune()`
  deletes keys by joining against `items`, so these rows are never pruned: one
  per day per channel, ~730 a year, cheaper than a second mechanism.

Sent through each channel's `alert()` rather than `send()` - a summary is
sentences, not a list of links, which is the payload `alert()` was shaped for.
On Telegram that means no `parse_mode`, so an em dash or a stray `<` from a
model cannot cost the message. See [[notify-channels]].

The page is rewritten with a fresh summary every cycle regardless. That
asymmetry is the design: a page is somewhere you go, a message is something that
interrupts you, and forty-eight interruptions a day saying roughly the same
thing is how a channel gets muted - taking P6-2's outage alerts with it.

## On the page

`render.write(..., summary=None)` renders `<section class="summary">` above the
groups: one `<p>` per non-empty line, the half before the first em dash in
`<strong>`. A line carrying no separator is rendered whole rather than dropped -
a model that ignored the format still wrote a sentence. Everything goes through
`html.escape`: this text came off somebody else's endpoint, answering every
thirty minutes, and it is the same trust boundary a feed title crosses. A falsy
summary renders nothing at all, which is the shipped case.

## Config

`ai.*` and `OPENAI_API_KEY` are specified in [[config-and-env]]. The section
ships inert: `ai.enabled` is `false`, so a config that says nothing about `ai`
upgrades into this version and behaves exactly as it did before.
