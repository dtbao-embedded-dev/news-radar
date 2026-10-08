---
title: Headline Vectors - similar.py
category: interface
purpose: The embeddings client that lets notify.cluster() join headlines saying the same thing in different words, its OpenAI-compatible contract, the measured model and threshold, and the rule that it can only ever add a cluster link and never cost a cycle.
status: active
updated: 2026-10-08
source: src/news_radar/similar.py, src/news_radar/notify/__init__.py, src/news_radar/__main__.py, src/news_radar/config.py, docker/docker-compose.yml
confidence: confirmed
keywords: similar, embed, vectors, embeddings, /v1/embeddings, all-minilm, all-MiniLM-L6-v2, cosine, threshold, similar.enabled, similar.api_url, similar.model, similar.threshold, similar.timeout_s, ollama, sidecar, profile similar, cluster, paraphrase, near-duplicate, _vectors
order: 9
---

# Headline Vectors - `similar.py`

> One request a cycle turns every headline about to be planned into a unit
> vector. `notify.cluster()` then treats two headlines as one event when their
> words overlap **or** their cosine reaches `similar.threshold`. Off by default;
> a failure falls back to words alone.

## Signatures

```
embed(fetcher, api_url, model, texts)   -> [unit vector] | None
vectors(fetcher, api_url, model, rows)  -> {dedup_key: unit vector}
```

| Function | Contract |
|----------|----------|
| `embed()` | One POST `{"model", "input": [texts]}`. Read back `data[*].embedding` **by `index`**, not by position. Every vector is scaled to length 1, so a dot product is the cosine. `[]` for no texts (no request); `None` for any failure: HTTP error, non-JSON, a missing index, a zero vector, or an empty url |
| `vectors()` | Embeds `item.title_key(title)` (the same folded, de-bylined text the word overlap reads), **once per `dedup_key`** even when a story has a row in two groups. `{}` when `embed()` failed |

Layer 5, imports layer 1 (`Fetcher.post_json`) and `item.title_key`. No config,
no clock, no store. No third dependency: the wire format is the contract, so
Ollama, vLLM, SGLang or a hosted API all work.

## Wiring

`__main__._vectors(cfg, rows, labels)` runs inside `_notify()` once a cycle,
after `_rows_to_send()` and before either channel is planned. Both channels
share the answer. It returns `{}` without touching the network when
`similar.enabled` is false, and `{}` (plus a logged exception) if anything
raises. The map goes to `notify.pick(..., vectors, threshold)` and from there to
`cluster()`. See [[notify-channels]].

`cluster()` rule: a link exists if `_same_event(words)` **or** both rows have a
vector **and** `threshold` is set **and** `dot >= threshold`. Vectors only add
links, so a partial or empty map clusters no worse than words alone.

Only the messages change. The page, the store and `dedup_key` never see a
vector, which keeps clustering a selection step and never an identity one.

## Measured (2026-10-08, copy of the homelab store)

| Measure | Value |
|---------|-------|
| Word overlap alone, 145 stories pushed on 2026-10-07 | 2 pairs joined |
| + `all-minilm` at 0.75, messages for 10-06 / 10-07 | 157 -> 133 / 143 -> 125 |
| Clusters formed over both days (cross-group replay) | 23: 21 one event, 2 one theme |
| Ollama `0.34.2` vs fastembed ONNX of the same model | identical message counts |
| Embed a whole day (529 headlines), homelab CPU | 3.1 s |
| Model size | 45 MB |

Threshold bands on 10-07 (cosine of `title_key()` text): from 0.75 up, every
pair inspected was one event. Around 0.73 and below, theme pairs appeared, for
example two different columns on China leading open-source AI. `0.80` lets the
seven-way ChatGPT launch split again. Larger models were tried:
`nomic-embed-text` scores everything high (1142 pairs >= 0.60 against 164), and
`paraphrase-multilingual-MiniLM-L12-v2` ranked pairs the same as `all-minilm`.
So the smallest model was kept. 🟢

The replay clustered the pushed set as one list. `pick()` clusters **per
group**, so the live cut is somewhat smaller. Freed `@n` slots also refill with
other stories, so the day's total is still bounded by the caps.

## Deployment

The compose `ollama` service (profile `similar`, image pinned to `0.34.2`,
`OLLAMA_KEEP_ALIVE=-1`, volume `ollama_models`) pulls `all-minilm` on every
start, so a fresh volume never answers 404 "model not found". It publishes no
port. It is deliberately not watchtower-labelled, because a runtime upgrade can
move the vectors the threshold was measured against. See [[deployment-homelab]].

The homelab cannot reach the DGX (`172.16.0.194`), so the model has to run on
the homelab itself.

## Known limits

- English model. Vietnamese sources ship disabled (see [[news-sources]]). A
  Vietnamese headline will cluster poorly but never wrongly, because the word
  rule still applies.
- Clustering stays per group. The same event filed under `AI` and `ChatGPT` is
  still two clusters; `pick()` drops the second appearance only when it is the
  *same* `dedup_key`. 🟡
