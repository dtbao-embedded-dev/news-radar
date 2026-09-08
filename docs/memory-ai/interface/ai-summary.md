---
title: The AI Summary - summarize.py
category: interface
purpose: Every public signature of the AI summary layer, the OpenAI-compatible contract it speaks, the fallback that survives a free model being retired, and the rules that keep an optional feature from ever costing a cycle or paying for the same sentence twice.
status: active
updated: 2026-09-08
source: src/news_radar/summarize.py, src/news_radar/__main__.py, src/news_radar/store.py, src/news_radar/render.py, src/news_radar/notify/telegram.py, src/news_radar/notify/discord.py
confidence: confirmed
keywords: summarize, build_prompt, parse_answer, free_models, MODEL_TRIES, FREE_SUFFIX, model fallback, :free, retired model, /v1/models, SENTENCES_MAX, SUMMARY_MAX, ai_summary, excerpt, unsummarised, save_summaries, ai.enabled, ai.api_url, ai.model, ai.timeout_s, max_per_run, OPENAI_API_KEY, chat completions, OpenAI-compatible, OpenRouter, Ollama, per-story summary, P6-4
order: 8
---

# The AI Summary - `summarize.py`

> One sentence under each story, in Vietnamese, from any endpoint speaking the
> OpenAI chat-completions wire format. Written once per story and stored. Off by
> default, and constitutionally unable to fail a cycle - and when the model it
> was pointed at stops existing, it finds another one rather than going quiet.

## Signatures

```
SENTENCES_MAX = 1
SUMMARY_MAX = 220
EXCERPT_IN_PROMPT = 320
MODEL_TRIES = 3
FREE_SUFFIX = ":free"

build_prompt(rows)                                     -> str
parse_answer(text, rows)                               -> {dedup_key: str}
free_models(fetcher, api_url)                          -> [str]
summarize(fetcher, api_url, api_key, model, rows)      -> {dedup_key: str}
```

Three private helpers carry the fallback, named here because the signature
above no longer says what one call does:

| Helper | Contract |
|--------|----------|
| `_models_url(api_url)` | `.../chat/completions` -> `.../models`, or `""` for a url that is not one. `rpartition` on the suffix, not a url parser - the whole reason `ai.api_url` is a full completions url is that providers disagree about where the base ends |
| `_candidates(fetcher, api_url, model)` | A **generator**: the pinned model, then `free_models()` minus it. Lazy is the contract, not an implementation detail - a working pin must never pay for the GET |
| `_ask(..., model, prompt)` | One completion. The text, or `None` for every failure alike: a refusal, a proxy's HTML, an undocumented body, and a 200 carrying `""` all mean *try the next one* |

`rows` is a **list** of the row shape `store.day_matches()` returns - the
caller's order is the prompt's numbering, and the only thing mapping an answer
back onto a story. See [[storage-layer]] for the row's fields, `excerpt` and
`ai_summary` included.

Layer 5, importing **layer 1** only - the same widening `notify/*` and `ops.py`
already take. No config, no clock, no store: everything arrives as an argument,
which is why `tests/test_summarize.py` exercises every path against a local
`http.server` with nothing installed. See [[module-layout]].

## Why per story, not per topic

Until 2026-09-07 this file wrote one paragraph per keyword group, rendered at
the top of the page and pushed to the channels as one message a local day. A
reader then got that message **and** the list of links - the same day described
twice, and the message that arrived second was the one nobody read. The sentence
now rides with the story it describes, on the page and in the notification, and
there is no separate summary message at all.

What went with it: `daily_key()`, `ai.notify_at_hour`, `ai.max_per_topic`,
`__main__._send_summary()`, `render._summary()` and `section.summary`.

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

**One request per cycle, not one per story.** The whole batch is numbered into a
single prompt; a per-story call would be twenty requests every thirty minutes
against a free tier that rate-limits well below that. Still one request whenever
the pinned model answers; a pin that fails costs one GET and at most
`MODEL_TRIES` completions - see below.

`temperature` is low but not zero: a summary read every day should not be the
same four sentences with the nouns swapped, and nothing here needs
reproducibility.

## When a free slug is retired

**The outage this exists for, measured.** OpenRouter withdrew the free tier of
`minimax/minimax-m3` on 2026-09-08. The pinned `minimax/minimax-m3:free`
answered `404 This model is unavailable for free. The paid version is available
now - use this slug instead: minimax/minimax-m3` to **every cycle for nine
hours**: 54 cycles, a `held for the next cycle` count that climbed to 27, and a
page and two channels that went out each time with no sentence under any story.
Nothing broke - that is the design working - and nothing alerted, which is the
design's cost. One WARNING a cycle, in a log nobody was reading.

A config file cannot be right about this. The endpoint's own list can:

```
GET  {api_url minus /chat/completions}/models
     -> keep the ids ending in `:free`
     -> drop the ones structurally incapable of a summary
     -> try them in the list's own order
```

**The pin goes first, always.** `ai.model` is the operator's measured choice and
a list ordered by release date is not an opinion about which model writes the
better Vietnamese sentence. Discovery is a generator, so a cycle whose pin
answers makes no GET at all and this file behaves exactly as it did before the
fallback existed. That is also what keeps a paid deployment paid-for: nothing
silently reaches for a free model while the billed one still works.

**The order is the provider's, because nothing better is on offer.** OpenRouter
returns `/models` newest-first by `created`, and "most recently released" is the
only field in the payload that correlates with "still served". The API publishes
nothing about quality, so nothing is invented here.

**`_NOT_A_SUMMARISER` excludes structure, not subject matter.** A `code` model,
a `content-safety` classifier, an `embed`der and a `rerank`er are not being
asked to write a sentence, and this is the only place that can be caught -
`parse_answer()` reads the number and nothing else. The **domain fine-tunes are
kept**, which was not the expectation: `ling-3.0-flash-sante` (health) and
`-fin` (finance) were the first things excluded, and measured twice on the real
prompt `-sante` answered **20 of 20** in idiomatic Vietnamese about GPUs and
datacentres in **13 s** - four times faster than anything else free. What a
model is asked about is the corpus, not what it was tuned on.

**`MODEL_TRIES = 3` is a cycle budget, not a retry policy.** Each attempt is a
real completion with the whole of `ai.timeout_s` behind it, inside a ten-minute
cycle that still has to render and notify. Measured on the same 20-story
prompt: 13 s, 66 s, 111 s - and `nemotron-3.5-lightning:free`, whose name
promises otherwise, took **533 s and 601 s** across two runs, answering 20 of 20
once and 0 of 20 the other. `ai.timeout_s` is all that stands between that model
and a cycle overrunning its own schedule.

**An endpoint with no free tier is the shipped case.** `api.openai.com` and a
local Ollama publish no `:free` id, so `free_models()` returns `[]`, the pin
stays the only candidate, and a 401 or a typo'd model id costs what it did
before: one warning, no summary. A url that is not a completions url never asks.

Verified live against OpenRouter on 2026-09-08 with the dead slug still pinned:
one 404, one GET, and `dots-studio/dots-3-note-preview:free` answered 20 of 20.

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

## The prompt: numbered stories, headline plus the source's own words

`build_prompt(rows)` emits one numbered block per row - the headline, and on the
next line the story's `excerpt` (the feed's own `<description>`, stripped and
capped by `item.new_item()`, cut again to `EXCERPT_IN_PROMPT` here). A story
whose source carried no description goes in on its title alone; that is the
normal case for a Reddit-style link post and never a reason to drop it.

The instruction is written in English (everything in this repository is) and
asks for a Vietnamese answer in one shape:

```
<number>. <at most SENTENCES_MAX sentence>
```

No links, no numbering beyond that, no heading, no preamble, and no skipped
number. `build_prompt()` is pure and returns `""` for no rows, which
short-circuits `summarize()` before any request.

## Reading the answer back

`parse_answer(text, rows)` matches `^\W*(\d{1,3})\s*[.):\-–—]\s*[*_]*\s*(.+)$`
per line. Models agree about the number and disagree about everything around
it - `- **1.** ...` is why the `[*_]*` after the separator is there, not
decoration.

| Case | Handling |
|------|----------|
| Number in `1..len(rows)` | Mapped onto that row; **first line wins** if repeated |
| Number outside the range | Dropped, never clamped - a wrong summary under a real headline is worse than none |
| A row the model skipped | Comes back `""` |
| A model that wrote a paragraph | Clipped to `SUMMARY_MAX`, on a word boundary |

`SUMMARY_MAX` is not cosmetic: every channel splits on a size budget, so an
unbounded sentence would not make one long line, it would make three times as
many messages.

**Every row asked about comes back with an entry.** `""` is the record that this
story *was* asked about - `store.save_summaries()` writes it, and
`store.unsummarised()` selects on `ai_summary IS NULL`, so a headline no model
can say anything about is never re-asked.

## One failure mode: `{}`

`summarize()` never raises. Each of these is a page whose stories carry no
sentence and messages that go out exactly as they did before the feature:

| Cause | Handling |
|-------|----------|
| Empty `api_url` | Returns before any request |
| No rows | Returns before any request |
| `HttpError` - refused, timed out, 4xx, 5xx | WARNING, **the next candidate** |
| A 200 that is not JSON (a proxy's HTML error page) | WARNING, **the next candidate** |
| A body missing `choices` / `message` / `content` | WARNING, **the next candidate** |
| An empty answer | WARNING, **the next candidate** |
| An unreadable `/models` | WARNING, no fallback - the pin was already tried |
| Every candidate exhausted, or `MODEL_TRIES` reached | WARNING naming each one tried, `{}` |

The four middle rows used to end in `{}` and now end in the next model. What
they still preserve is unchanged: `{}` means *no story was answered at all*, so
the rows stay `NULL` and the next cycle retries them.

`{}` rather than a mapping of empty strings, and the distinction matters: a
failed **request** must leave those stories unasked so the next cycle retries
them, while a request that was answered and skipped a line marks that story
done.

**And the caller adds nothing to `problems`.** An endpoint having a bad
afternoon is not a news-radar outage: it must never withhold the heartbeat ping
or trip an ops alert. The optional thing may not speak for the thing that is
not - the mirror of the asymmetry in [[delivery-phases]] where a refused ping is
a warning and a dead site is a problem.

## Once per story, in its life

`__main__._summarize(cfg, conn, day, labels)` runs inside `_publish()`, on the
same `day` rows the page renders and the messages are built from. It is the only
caller, and it does four things:

1. Flattens `day` into page order and asks `store.unsummarised()` which of those
   keys have `ai_summary IS NULL`.
2. Takes the first `ai.max_per_run` (default 20) of them and logs how many were
   held for the next cycle.
3. Calls `summarize()` once.
4. Writes the answers with `store.save_summaries()` **and** mutates the rows in
   `day`, so the page rendered a few lines later is not a cycle behind.

The cap is what stops a first run against a store full of yesterday's stories
sending one enormous prompt; the backlog drains over the following cycles, in
page order.

**The store is the cache.** The page is rebuilt from the whole local day every
thirty minutes, so without `ai_summary` on `items` a story that stays on the
page all day would be paid for forty-eight times. Measured on a three-story
smoke run with `max_per_run: 2`: cycle 1 sent one completion for two stories,
cycle 2 one for the third, cycle 3 none at all.

`_publish()` returns the `run_id` alone.

## On the page and in the message

The same sentence in the same position in all three renderers - a reader
comparing the page with their phone should be comparing one report with itself:

| Renderer | Shape |
|----------|-------|
| `render._story()` | `<p class="gist">` inside the story's `<li>`, spanning both grid columns under the title |
| `notify/telegram._line()` | `• <a>title</a>` ⏎ `<i>“gist”</i>` ⏎ `<i>time</i>`, or `• <a>title</a> <i>time</i>` on one line with no gist |
| `notify/discord._line()` | `• [title](url)` ⏎ `-# “gist”` ⏎ `` `time` ``, or ``• [title](url) `time` `` on one line with no gist (`-#` is Discord's subtext, and only works at the start of a line) |

Everything goes through each channel's own escaper - `html.escape` for the page
and Telegram, the Markdown backslash rule for Discord. This text came off
somebody else's endpoint answering every thirty minutes: the same trust boundary
a feed title crosses, reached from a new direction. See [[notify-channels]].

**An empty `ai_summary` renders no element at all** - no blank paragraph, no
empty quotes, no stray `-#`, and the timestamp stays on the title's line rather
than dropping to one of its own. That is the shipped case (`ai.enabled: false`),
and the message is then byte-for-byte the one this project sent before. The time
only moves down when there is a sentence between them to move it: a bare title
and a bare timestamp on two lines is a taller message saying exactly as much.

A summarised story is three lines instead of one, so a chunk holds roughly a
third as many stories and a run makes more messages than it used to.
`notify.chunk()` still guarantees the budget and still never splits a story.

## Config

`ai.*` and `OPENAI_API_KEY` are specified in [[config-and-env]]. The section
ships inert: `ai.enabled` is `false`, so a config that says nothing about `ai`
upgrades into this version and behaves exactly as it did before.
