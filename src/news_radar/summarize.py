"""The day's matches, one line per topic, from an OpenAI-compatible endpoint.

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

Two rules govern the whole file:

- **The summary is per topic, and a quiet topic is not in it.** One line per
  keyword group: the group's name, then at most `SENTENCES_MAX` sentences about
  what actually stood out. A group whose day held nothing notable is left out of
  the prompt entirely, so the model is never handed a topic it would have to
  fill with "nothing today" - which is how a daily message becomes a wall of
  text nobody finishes reading.
- **A summary is optional, so nothing here may raise.** The page and the
  notification are already written by the time this is asked; an endpoint having
  a bad afternoon must cost a log line and never a cycle.

Contract: docs/memory-ai/interface/config-and-env.md (`ai.*`)
"""

from __future__ import annotations

import json
import logging

from .fetch.http import HttpError

__all__ = ["summarize", "build_prompt", "SENTENCES_MAX"]

log = logging.getLogger("news_radar.summarize")

# The whole reason the daily message stays a glance. Two sentences a topic is
# enough to say what happened and why it is worth a click, and short enough that
# ten topics still fit on a phone screen without scrolling into resentment.
SENTENCES_MAX = 2

# Written in English because everything in this repository is; the *answer* is
# Vietnamese because that is who reads the page. `{n}` is SENTENCES_MAX.
INSTRUCTION = """\
You are summarising a news radar's matches for today, grouped by topic.

Write the answer in Vietnamese. Output one line per topic, in the order the
topics are given below, formatted as:

    <topic name> — <at most {n} sentences>

Say what actually stood out and why it matters. Do not repeat headlines
verbatim, do not add links, do not number the lines, and do not write any
heading, preamble or closing remark. If a topic's stories are unremarkable,
omit that topic's line entirely rather than writing that nothing happened.

Topics and their top stories:
"""


def build_prompt(rows_by_label, labels, max_per_topic):
    """`{label: [row]}` -> the prompt text, or `""` when nothing is notable.

    Pure: no clock, no network, no config. Every decision about *what the model
    is even shown* is made here and can be checked without a socket.

    `labels` is the group order the keyword file fixes - the same order the page
    renders in, so the summary reads down the page rather than across a mapping
    whose order would shuffle between runs. Within a group the rows arrive
    already sorted `score DESC` by `store._matches()`, so "the notable ones" is
    a slice and not a second ranking pass.
    """
    blocks = []
    for label in labels:
        rows = (rows_by_label.get(label) or [])[:max_per_topic]
        if not rows:
            # Left out on purpose, not rendered empty. See the module docstring.
            continue
        titles = "\n".join(
            "  - {}".format(row.get("title") or "") for row in rows)
        blocks.append("{}:\n{}".format(label, titles))

    if not blocks:
        return ""
    return INSTRUCTION.format(n=SENTENCES_MAX) + "\n" + "\n\n".join(blocks)


def summarize(fetcher, api_url, api_key, model, rows_by_label, labels,
              max_per_topic):
    """One completion. Returns the summary text, or `None` for every failure.

    `None` is the only failure mode this function has. A refused request, a
    timeout, a proxy answering HTML with a 200, a body shaped like nothing the
    API documents - each is a page without a summary block and a message that
    does not go out, never a cycle that stops.

    The three short-circuits above the request are not politeness: an empty key,
    an empty url or a day with no story would each be a bill for asking a
    question with nothing in it.
    """
    if not api_url or not (api_key or "").strip():
        return None

    prompt = build_prompt(rows_by_label, labels, max_per_topic)
    if not prompt:
        log.info("summary: nothing notable today, so nothing was asked")
        return None

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
            headers={"Authorization": "Bearer {}".format(api_key)},
        )
    except HttpError as exc:
        log.warning("summary: the endpoint refused (%s) - the page and the "
                    "messages go out without one", exc)
        return None

    try:
        payload = json.loads(body.decode("utf-8", "replace"))
        text = (payload["choices"][0]["message"]["content"] or "").strip()
    except (ValueError, AttributeError, KeyError, IndexError, TypeError) as exc:
        # Every provider claims this shape and one of them will be wrong. A
        # KeyError from an endpoint is not a bug in the radar.
        log.warning("summary: the answer was not in the documented shape (%s: "
                    "%s)", type(exc).__name__, exc)
        return None

    if not text:
        log.warning("summary: the endpoint answered with an empty summary")
        return None

    log.info("summary: %d character(s) over %d topic(s)",
             len(text), len(text.splitlines()))
    return text
