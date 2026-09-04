---
title: TrendRadar Is the Reference Repo When You Get Stuck
category: rule
purpose: When and how to consult TrendRadar for a problem news-radar hits, and exactly what may not be carried back.
status: active
updated: 2026-09-04
source: https://github.com/sansan0/TrendRadar, docs/memory-ai/adr/adr-0001-clean-room-from-trendradar.md
confidence: confirmed
keywords: TrendRadar, reference, stuck, GPL-3.0, clean-room, copyleft, prior art, how to consult
order: 3
---

# TrendRadar Is the Reference Repo When You Get Stuck

> `https://github.com/sansan0/TrendRadar` is not upstream and is never merged
> from. It is the **reference to open when a specific problem is hard**: read how
> they solved it, understand the approach, then come back and write our own.

## When to open it

Not routinely. Open it when a concrete step of news-radar misbehaves and the
answer is not obvious - a feed returning junk, dedup collapsing the wrong stories,
a Telegram message failing to parse, a page rendering wrong, a ranking that puts
noise on top. TrendRadar has been in production for a long time at a scale
news-radar has not seen; it has already been bitten by most of it.

Do **not** open it to decide what news-radar should be. That is what
[[delivery-phases]] is for.

## Where to look, by problem

| Stuck on | Go read |
|----------|---------|
| The overall crawl to filter to render to push flow | Its package entrypoint (`python -m trendradar`) |
| How to name and layer configuration keys | `config/config.yaml` |
| Keyword-file syntax: groups, required and excluded words, global filters | `config/frequency_words.txt` and the README section describing it |
| Message formatting per channel: escaping, splitting, batching | Its notification adapters (feishu, telegram, slack, and the rest) |
| Report page layout: dark mode, tabs, in-page search | The `index.html` it generates |
| Ranking that behaves sensibly | Its `advanced.weight.rank` / `frequency` / `hotness` split |
| Which platform ids and endpoints exist at all | Its newsnow integration - useful as prior art even though news-radar uses RSS |

Both projects solve the same shape of problem, so the *questions* transfer even
where the answers do not: news-radar reads RSS and keyword-built search feeds,
TrendRadar reads Chinese hot-lists through the newsnow API.

## What may cross over, and what may not

TrendRadar is **GPL-3.0**. Copying its expression into news-radar makes
news-radar a derivative work and pulls the copyleft with it. That is the reason
for the line below, not an aesthetic preference - see
`adr/adr-0001-clean-room-from-trendradar.md`.

| Allowed | Not allowed |
|---------|-------------|
| An approach restated in your own words: "they split the ranking weight into three terms" | Source code, in any amount |
| A fact about the world: an API endpoint, a documented rate limit, a message-size limit | Function, class, or module names |
| A problem you did not know existed: "titles arrive with markup, strip it first" | File and directory structure |
| A design question worth asking: "should a keyword group cap its own output?" | Constant values, message-format strings |
| | A configuration schema copied key for key |

Practical test before you write the line: **close the tab first.** If you cannot
write it from memory in your own structure, you are copying, not learning.

## Recording what you learned

When consulting it changes a decision here, write the decision into this bank in
news-radar's own terms - a `behavior/` or `data/` doc, or an ADR if it settles a
question that could be re-litigated. Say in prose that the idea came from
TrendRadar. Do not reproduce the upstream artifact to explain it.
