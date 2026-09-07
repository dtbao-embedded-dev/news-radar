"""One sentence per story, from an OpenAI-compatible endpoint.

Layer 5, beside `render.py`, `notify/` and `ops.py`. Like them it imports
**layer 1** for the transport and nothing else - no config, no clock, no store.
The url, the key, the model and the rows all arrive as arguments, which is why
`tests/test_summarize.py` exercises every path against a local `http.server`
with nothing installed and nothing configured.

**No third dependency.** P6-4 was dropped once for costing an API key, a bill
and an `openai` package against a two-dependency rule the project has held since
P0. P4's `Fetcher.post_json()` retired the third of those: an OpenAI-compatible
`/v1/chat/completions` is one POST with a bearer header, and the wire format
rather than the vendor is what is being spoken here - OpenRouter, DeepSeek, Groq
and a local Ollama all answer it, and the last has no bill either.

Three rules govern the whole file:

- **The summary is per story, and it rides with the story.** The day used to be
  summarised by topic into one paragraph at the top of the page and one message
  a day; the reader then got that *and* the list of links, which is the same
  day described twice. A sentence under each headline is the same information
  where the reader already is.
- **A story is summarised once in its life.** The caller passes only the rows
  the store has no summary for, and writes the answers back. The page is
  rebuilt every thirty minutes from the whole day's rows, so re-asking would be
  the same completion paid for forty-eight times.
- **A summary is optional, so nothing here may raise.** The page and the
  notification are already written by the time this is asked; an endpoint
  having a bad afternoon must cost a log line and never a cycle.

Contract: docs/memory-ai/interface/config-and-env.md (`ai.*`)
"""

from __future__ import annotations

import json
import logging
import re

from .fetch.http import HttpError

__all__ = ["summarize", "build_prompt", "parse_answer", "SENTENCES_MAX",
           "SUMMARY_MAX"]

log = logging.getLogger("news_radar.summarize")

# The whole reason a message stays a glance. One sentence a story is what fits
# under a headline on a phone without turning a twenty-story list into a page
# of prose nobody finishes.
SENTENCES_MAX = 1

# The hard stop, applied to whatever comes back. Every channel splits on a size
# budget, so a model that ignores the sentence count and writes a paragraph
# would not produce one long line - it would produce three times as many
# messages. Cut here rather than letting that happen downstream.
SUMMARY_MAX = 220

# How much of a story's own excerpt reaches the prompt. Shorter than
# `item.EXCERPT_MAX` on purpose: the store keeps the fuller text because it
# costs nothing to keep, while every character here is paid for once per story
# and the first two sentences of a teaser carry the subject.
EXCERPT_IN_PROMPT = 320

# Written in English because everything in this repository is; the *answer* is
# Vietnamese because that is who reads the page. `{n}` is SENTENCES_MAX.
INSTRUCTION = """\
You are summarising the stories a news radar found today. Each one is numbered,
with its headline and - when the source gave one - the source's own description.

Write the answer in Vietnamese. Output one line per story, in the order given,
formatted exactly as:

    <number>. <at most {n} sentence>

Say what the story is actually about and why it is worth opening. Do not repeat
the headline verbatim, do not add links, do not write any heading, preamble or
closing remark, and do not skip a number. If a story's headline and description
say too little to summarise, write its number followed by the headline's own
subject in a few words rather than dropping the line.

Stories:
"""

# `1.` / `1)` / `1 -` / `**1.**`, with or without leading bullet junk. Models
# agree on the number and disagree about everything around it, and the number
# is the only part that has to be read correctly. The `[*_]*` after the
# separator is not decoration: `- **1.** Một.` closes its bold *after* the dot,
# and without it the summary starts with a stray `**`.
_NUMBERED = re.compile(r"^\W*(\d{1,3})\s*[.):\-–—]\s*[*_]*\s*(.+)$")


def _clip(text):
    """`text` cut to SUMMARY_MAX, on a word boundary when there is one near."""
    text = " ".join((text or "").split())
    if len(text) <= SUMMARY_MAX:
        return text
    cut = text[:SUMMARY_MAX]
    space = cut.rfind(" ")
    if space > SUMMARY_MAX - 40:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "…"


def build_prompt(rows):
    """`[row]` -> the prompt text, or `""` when there is nothing to ask about.

    Pure: no clock, no network, no config. Every decision about *what the model
    is even shown* is made here and can be checked without a socket.

    The rows arrive in the caller's order and the numbering is positional, so
    `parse_answer()` can map an answer back onto them by index alone - no key,
    no title matching, and nothing for a model to get wrong except the number.
    """
    lines = []
    for index, row in enumerate(rows, start=1):
        block = "{}. {}".format(index, (row.get("title") or "").strip())
        excerpt = " ".join((row.get("excerpt") or "").split())
        if excerpt:
            block += "\n   {}".format(excerpt[:EXCERPT_IN_PROMPT])
        lines.append(block)

    if not lines:
        return ""
    return INSTRUCTION.format(n=SENTENCES_MAX) + "\n" + "\n\n".join(lines)


def parse_answer(text, rows):
    """The model's numbered lines -> `{dedup_key: summary}` for `rows`.

    Every row handed in comes back with an entry, answered or not: an unmatched
    row maps to `""`, which `store.save_summaries()` writes as "asked, nothing
    useful" so the story is never re-asked. A story costing a completion every
    cycle because one model once skipped its line is the failure this avoids.

    A number outside `1..len(rows)` is dropped rather than clamped - a model
    that invented a story is not describing one of these, and attaching its
    sentence to whichever row is nearest would put a wrong summary under a real
    headline.
    """
    found = {}
    for line in (text or "").splitlines():
        match = _NUMBERED.match(line.strip())
        if not match:
            continue
        index = int(match.group(1))
        if 1 <= index <= len(rows):
            # First line wins: a model that repeats a number is restating, and
            # the restatement is where a preamble usually ends up.
            found.setdefault(index, _clip(match.group(2)))

    return {row["dedup_key"]: found.get(index, "")
            for index, row in enumerate(rows, start=1)}


def summarize(fetcher, api_url, api_key, model, rows):
    """One completion for the whole batch. `{dedup_key: summary}`, or `{}`.

    An empty mapping is the only failure mode this function has. A refused
    request, a timeout, a proxy answering HTML with a 200, a body shaped like
    nothing the API documents - each is a page whose stories carry no sentence
    and messages that go out as they did before, never a cycle that stops. `{}`
    rather than a mapping of empty strings on purpose: a failed *request* must
    leave the stories unasked, so the next cycle tries them again.

    **An empty `api_key` is a supported deployment, not a failure.** An SGLang,
    vLLM or Ollama on the LAN authenticates nobody; sending it
    `Authorization: Bearer ` is at best ignored and at worst a 401 from whatever
    sits in front of it, so with no key the header is simply not sent.

    The two short-circuits above the request are not politeness: an empty url or
    a cycle that found no new story would each be a bill for asking a question
    with nothing in it.
    """
    if not api_url:
        return {}

    rows = list(rows)
    prompt = build_prompt(rows)
    if not prompt:
        return {}

    key = (api_key or "").strip()
    try:
        body = fetcher.post_json(
            api_url,
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                # Low, not zero: a summary read every day should not be the
                # same four sentences with the nouns swapped, and nothing here
                # needs reproducibility.
                "temperature": 0.3,
            },
            headers={"Authorization": "Bearer {}".format(key)} if key else None,
        )
    except HttpError as exc:
        log.warning("summary: the endpoint refused (%s) - the page and the "
                    "messages go out without one", exc)
        return {}

    try:
        payload = json.loads(body.decode("utf-8", "replace"))
        text = (payload["choices"][0]["message"]["content"] or "").strip()
    except (ValueError, AttributeError, KeyError, IndexError, TypeError) as exc:
        # Every provider claims this shape and one of them will be wrong. A
        # KeyError from an endpoint is not a bug in the radar.
        log.warning("summary: the answer was not in the documented shape (%s: "
                    "%s)", type(exc).__name__, exc)
        return {}

    if not text:
        log.warning("summary: the endpoint answered with an empty summary")
        return {}

    summaries = parse_answer(text, rows)
    answered = sum(1 for value in summaries.values() if value)
    log.info("summary: %d of %d story(ies) answered", answered, len(rows))
    return summaries
