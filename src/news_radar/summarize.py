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

__all__ = ["summarize", "build_prompt", "parse_answer", "free_models",
           "SENTENCES_MAX", "SUMMARY_MAX", "MODEL_TRIES"]

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

# How many models one cycle will ask before it gives up. A free slug fails in
# five different ways - retired (404), rate-limited upstream (429), paid-only
# (402), harness-only (403), and a 200 with an empty body - so trying the next
# one is what keeps the feature alive across a retirement. The cap is what
# stops it eating the cycle: every attempt is a real request with the full
# `ai.timeout_s` behind it, and the page still has to render and notify.
MODEL_TRIES = 3

# The suffix a provider puts on a slug it serves for nothing. OpenRouter's
# convention, and the only machine-readable "this costs no money" the list has.
FREE_SUFFIX = ":free"

# A `:free` id is not automatically a summariser, and this is the only place a
# wrong one can be caught - `parse_answer()` reads the number and nothing else,
# so it cannot tell a bad summary from a good one. Structural mismatches only:
# a code model, a safety classifier, an embedder or a reranker is not being
# asked to write a sentence about the news.
#
# The domain fine-tunes are deliberately **not** here, against expectation.
# `inclusionai/ling-3.0-flash-sante` is a health tune and `-fin` a finance one,
# and both looked like obvious exclusions; measured twice on the real 20-story
# prompt, `-sante` answered **20 of 20** in correct, idiomatic Vietnamese about
# GPUs and datacentres in 13 s - four times faster than anything else on the
# free list. What a model is asked about is the corpus, not what it was tuned
# on.
_NOT_A_SUMMARISER = ("code", "content-safety", "guard", "embed", "rerank")

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


def _models_url(api_url):
    """`.../v1/chat/completions` -> `.../v1/models`, or `""` when it is not one.

    String surgery rather than a url parser, and deliberately: `ai.api_url` is
    spelled as a whole completions url in the first place because providers
    disagree about where the base ends - only some of them put it under `/v1`.
    The one thing they do agree on is that suffix, so it is the only thing
    worth keying off. Anything else - a gateway on its own path shape - gets
    `""`, which skips discovery rather than guessing a url and 404ing on it.
    """
    base, sep, _ = (api_url or "").rpartition("/chat/completions")
    return base + "/models" if sep else ""


def free_models(fetcher, api_url):
    """The endpoint's free model ids, newest first, or `[]`. Never raises.

    This exists because a free slug is retired without notice and a pinned one
    then fails forever. Measured: `minimax/minimax-m3:free` answered for two
    days, then returned 404 "This model is unavailable for free" on **every
    cycle for nine hours** - fifty-four cycles of pages and notifications that
    went out with no sentence under any story, behind one WARNING a cycle that
    nobody was reading. The endpoint own list is right the day after a
    retirement, which a config file is not.

    The order is the list own - OpenRouter returns it newest-first by
    `created` - and newest is the best proxy available for "still served". The
    API publishes nothing about quality to sort on, so nothing is invented
    here: `_NOT_A_SUMMARISER` drops the ids that are wrong for the job and the
    rest are tried in the order the provider gave them.

    **An endpoint with no free tier answers this with `[]`, which is the
    shipped case.** `api.openai.com` and a local Ollama publish no `:free` id
    at all, so the pinned model stays the only candidate and this file behaves
    exactly as it did before the fallback existed.
    """
    url = _models_url(api_url)
    if not url:
        return []

    try:
        payload = json.loads(fetcher.get(url).decode("utf-8", "replace"))
        ids = [entry["id"] for entry in payload["data"]]
    except (HttpError, ValueError, AttributeError, KeyError, TypeError) as exc:
        # A list that cannot be read is one fallback that will not happen, not
        # a failure of its own: the caller has already tried the pinned model
        # by the time this runs.
        log.warning("summary: the model list is unreadable (%s: %s)",
                    type(exc).__name__, exc)
        return []

    return [name for name in ids
            if isinstance(name, str) and name.endswith(FREE_SUFFIX)
            and not any(bad in name.lower() for bad in _NOT_A_SUMMARISER)]


def _candidates(fetcher, api_url, model):
    """The pinned model, then the endpoint free ones. A generator on purpose.

    Discovery costs a GET, and a cycle whose pinned model answers must never
    pay for it - which is what keeps the normal path the same single request it
    was before, right up until the day the pin stops working.

    The pin goes first even when it is itself a free slug: it is the operator
    measured choice, and a list ordered by release date is not an opinion about
    which model writes the better Vietnamese sentence.
    """
    pinned = (model or "").strip()
    if pinned:
        yield pinned
    for candidate in free_models(fetcher, api_url):
        if candidate != pinned:
            yield candidate


def _ask(fetcher, api_url, key, model, prompt):
    """One completion from one model. Its text, or `None` for any failure.

    `None` for all of them on purpose - a refusal, a proxy HTML page, a body
    shaped like nothing the API documents, and a 200 carrying an empty string
    are the same fact to the caller: this model did not answer, try the next.
    The 200-with-nothing case is not hypothetical, it is measured:
    `nvidia/nemotron-3-super-120b-a12b:free` returns an empty body under load.

    Every branch names the model in its log line. With a fallback in play,
    "the endpoint refused" without a name is a log nobody can act on.
    """
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
        log.warning("summary: %s refused (%s)", model, exc)
        return None

    try:
        payload = json.loads(body.decode("utf-8", "replace"))
        text = (payload["choices"][0]["message"]["content"] or "").strip()
    except (ValueError, AttributeError, KeyError, IndexError, TypeError) as exc:
        # Every provider claims this shape and one of them will be wrong. A
        # KeyError from an endpoint is not a bug in the radar.
        log.warning("summary: %s answered outside the documented shape (%s: "
                    "%s)", model, type(exc).__name__, exc)
        return None

    if not text:
        log.warning("summary: %s answered with an empty summary", model)
        return None
    return text


def summarize(fetcher, api_url, api_key, model, rows):
    """One completion for the whole batch. `{dedup_key: summary}`, or `{}`.

    An empty mapping is the only failure mode this function has. A refused
    request, a timeout, a proxy answering HTML with a 200, a body shaped like
    nothing the API documents - each is a page whose stories carry no sentence
    and messages that go out as they did before, never a cycle that stops. `{}`
    rather than a mapping of empty strings on purpose: a failed *request* must
    leave the stories unasked, so the next cycle tries them again.

    **One request per cycle, until the pinned model stops working.** The pin is
    asked first and its answer ends the loop, so the common case is the single
    completion it always was. Only a model that fails reaches for
    `free_models()` - one GET, then up to `MODEL_TRIES` completions in total,
    which is what stops a provider retiring a free slug from taking the feature
    down until a human notices and edits a config file.

    **An empty `api_key` is a supported deployment, not a failure.** An SGLang,
    vLLM or Ollama on the LAN authenticates nobody; sending it
    `Authorization: Bearer ` is at best ignored and at worst a 401 from whatever
    sits in front of it, so with no key the header is simply not sent.

    The two short-circuits above the loop are not politeness: an empty url or a
    cycle that found no new story would each be a bill for asking a question
    with nothing in it.
    """
    if not api_url:
        return {}

    rows = list(rows)
    prompt = build_prompt(rows)
    if not prompt:
        return {}

    key = (api_key or "").strip()
    tried = []
    for candidate in _candidates(fetcher, api_url, model):
        tried.append(candidate)
        text = _ask(fetcher, api_url, key, candidate, prompt)
        if text:
            summaries = parse_answer(text, rows)
            answered = sum(1 for value in summaries.values() if value)
            # The model is named here because it is no longer necessarily the
            # one in the config file: an operator reading "17 of 20 answered"
            # needs to know which model wrote them, and therefore that the pin
            # has stopped working.
            log.info("summary: %d of %d story(ies) answered by %s",
                     answered, len(rows), candidate)
            return summaries
        if len(tried) >= MODEL_TRIES:
            break

    log.warning("summary: no model answered (tried %s) - the page and the "
                "messages go out without one", ", ".join(tried) or "none")
    return {}
