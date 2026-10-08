"""Headline vectors from an OpenAI-compatible `/v1/embeddings`, for clustering.

Layer 5, beside `summarize.py`, and built the same way: it imports **layer 1**
for the transport and `item.title_key()` for the text, and nothing else - no
config, no clock, no store. The url and the model arrive as arguments, which is
why `tests/test_similar.py` checks every path against a local `http.server`.

**What it is for.** `notify.cluster()` joins two headlines on word overlap, and
measured over the 145 stories pushed on 2026-10-07 that joined **2 pairs**.
The same day carried seven write-ups of one ChatGPT launch and five of one
teen-safety report, each worded too differently to share half their words. A
small sentence-embedding model reads them as one event: at cosine 0.75 under
`all-MiniLM-L6-v2` those 145 become 125 messages. Of the 23 clusters it
formed over 2026-10-06 and 10-07, 21 were one event and two were one theme -
two different columns on Chinese open-weight models, and two launches that
named the same rival.

**No third dependency.** One `Fetcher.post_json()`, the same as the summary:
Ollama, vLLM, SGLang and the hosted APIs all answer `/v1/embeddings`. A model
runtime inside this process would be onnxruntime and a tokenizer against the
two-dependency rule.

**Optional, so nothing here may raise.** Every failure is the same answer -
no vectors - and `cluster()` then joins on words alone, exactly as it did
before this file existed.

Contract: docs/memory-ai/interface/similar.md
"""

from __future__ import annotations

import json
import logging
import math

from .item import title_key

__all__ = ["embed", "vectors"]

log = logging.getLogger("news_radar.similar")


def _unit(vector):
    """`vector` scaled to length 1, or `None` for one with no direction."""
    norm = math.sqrt(sum(x * x for x in vector))
    if not norm:
        return None
    return [x / norm for x in vector]


def embed(fetcher, api_url, model, texts):
    """`[text]` -> `[unit vector]` in the same order, or `None` on any failure.

    One request for the whole batch. The answer is read by its `index` field,
    not by its position: the OpenAI contract numbers the items and an endpoint
    is free to return them in any order.

    Unit length is the contract the caller leans on - a dot product of two of
    these is their cosine, with no square root in `cluster()`'s inner loop.
    """
    if not texts:
        return []
    if not api_url:
        return None
    try:
        raw = fetcher.post_json(api_url, {"model": model, "input": list(texts)})
        data = json.loads(raw)["data"]
        by_index = {int(entry["index"]): entry["embedding"] for entry in data}
        out = []
        for index in range(len(texts)):
            vector = _unit([float(x) for x in by_index[index]])
            if vector is None:
                raise ValueError("a zero vector at index {}".format(index))
            out.append(vector)
        return out
    except Exception as exc:  # noqa: BLE001 - optional feature, one warning
        # A 404 from Ollama here almost always means the model was never
        # pulled; the message it carries says so, and is what gets logged.
        log.warning("similar: no vectors from %s (%s: %s); clustering on "
                    "words alone this cycle", model, type(exc).__name__, exc)
        return None


def vectors(fetcher, api_url, model, rows):
    """`[row]` -> `{dedup_key: unit vector}`, empty when the endpoint failed.

    The text embedded is `title_key()` - folded, de-bylined, de-punctuated -
    which is what the word overlap reads too, so a trailing `- Yahoo Finance`
    pulls two unrelated headlines together in neither. A story claimed by two
    groups has a row in each and is embedded once.
    """
    keys, texts, seen = [], [], set()
    for row in rows:
        key = row["dedup_key"]
        if key not in seen:
            seen.add(key)
            keys.append(key)
            texts.append(title_key(row["title"] or ""))
    got = embed(fetcher, api_url, model, texts)
    if not got:
        return {}
    return dict(zip(keys, got))
