---
title: The AI Summary - summarize.py
category: interface
purpose: Every public signature of the AI summary layer, the OpenAI-compatible contract it speaks, and the rules that keep an optional feature from ever costing a cycle or paying for the same sentence twice.
status: active
updated: 2026-09-07
source: src/news_radar/summarize.py, src/news_radar/__main__.py, src/news_radar/store.py, src/news_radar/render.py, src/news_radar/notify/telegram.py, src/news_radar/notify/discord.py
confidence: confirmed
keywords: summarize, build_prompt, parse_answer, SENTENCES_MAX, SUMMARY_MAX, ai_summary, excerpt, unsummarised, save_summaries, ai.enabled, ai.api_url, ai.model, max_per_run, OPENAI_API_KEY, chat completions, OpenAI-compatible, Ollama, per-story summary, P6-4
order: 8
---

# The AI Summary - `summarize.py`

> One sentence under each story, in Vietnamese, from any endpoint speaking the
> OpenAI chat-completions wire format. Written once per story and stored. Off by
> default, and constitutionally unable to fail a cycle.

## Signatures

```
SENTENCES_MAX = 1
SUMMARY_MAX = 220
EXCERPT_IN_PROMPT = 320

build_prompt(rows)                                     -> str
parse_answer(text, rows)                               -> {dedup_key: str}
summarize(fetcher, api_url, api_key, model, rows)      -> {dedup_key: str}
```

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
against a free tier that rate-limits well below that.

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
| `HttpError` - refused, timed out, 4xx, 5xx | WARNING, `{}` |
| A 200 that is not JSON (a proxy's HTML error page) | WARNING, `{}` |
| A body missing `choices` / `message` / `content` | WARNING, `{}` |
| An empty answer | WARNING, `{}` |

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
