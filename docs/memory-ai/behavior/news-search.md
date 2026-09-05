---
title: How News Is Searched, Matched and Ranked
category: behavior
purpose: The end-to-end crawl algorithm - which URLs are built, how a title is matched against a keyword group, how duplicates collapse, and how the shortlist is ordered.
status: active
updated: 2026-09-05
source: src/news_radar/fetch/, src/news_radar/__main__.py
confidence: confirmed
keywords: crawl, search algorithm, matching, diacritics, dedup, ranking, freshness, half-life, user-agent, 403, rate limit, edge cases
order: 1
---

# How News Is Searched, Matched and Ranked

> One run is six stages: build the URL list, fetch, normalise, match, collapse,
> rank. Every stage is pure except fetch, which is the only one that can fail
> partially - and it must fail partially rather than abort.

## Stage 1 - build the URL list

1. Read every `feeds[]` entry with `enabled: true`. Each contributes one URL.
2. Parse `frequency_words.txt` into groups. Take each group's **primary term**
   (its first plain line), skipping `[GLOBAL_FILTER]`.
3. For every enabled `search_templates[]` entry, substitute each primary term into
   `{kw}`, percent-encoded. A multi-word term is wrapped in quotes first so the
   search engine treats it as a phrase.
4. The result is one flat list of `(url, source_id, keyword_group | None)`.

Cost is predictable and worth stating out loud: `len(feeds) + len(groups) x
len(enabled templates)`. Measured on the shipped config: eight feeds, seven
groups and two enabled templates is **22 requests and 35-57 s per run**, not
eight requests. `build_urls()` is pure, so that number is known before the first
byte goes out.

## Stage 2 - fetch

Requests are issued sequentially, grouped by host, honouring
`advanced.request_interval_ms` **per hostname**. Every request carries the
configured User-Agent, `advanced.request_timeout_s`, and up to
`advanced.max_retries` retries with exponential backoff.

**A failing source is recorded and skipped, never fatal.** The run's `errors` list
carries one entry per failed source; the report still renders from whatever
arrived.

## Stage 3 - normalise

Each response is parsed by its declared format (`rss`, `atom`, `hn_algolia_json`)
and mapped into the `NewsItem` shape - field mapping and URL canonicalisation are
in [[news-item]] and [[news-sources]]. HTML is stripped from titles here, once,
so no later stage has to think about markup.

## Stage 4 - match

For each item, for each group:

1. **Global filter first.** If any `!` line of `[GLOBAL_FILTER]` matches, the item
   is dropped entirely and no group sees it.
2. **Any-of.** At least one plain term or `/regex/` of the group must match.
3. **Required.** Every `+` term of the group must also match.
4. **Excluded.** No `!` term of the group may match.

Matching is done on a folded form of the title: lowercased, Unicode NFD, combining
marks removed, whitespace collapsed. So `Điện tử` matches `dien tu`, and `ESP32`
matches `esp32`. `/regex/` lines are applied to the **original** title, not the
folded one, because a regex author is entitled to write their own case rules.

An item may belong to several groups. It is counted once per group it matches.

A search-feed item carries the group whose term produced its query, but it is
**still matched normally** - the search engine's idea of relevance does not get a
free pass into the report.

## Stage 5 - collapse

Items are grouped by `dedup_key` ([[news-item]]). The survivor keeps the earliest
`published_at` and the union of `source_id`s. The size of that union is the
cross-source frequency signal - a story that showed up on Hacker News *and*
Lobsters *and* a Google News query is, empirically, the story of the day.

## Stage 6 - rank

Per group, each surviving item scores:

```
score = w_source    * max(rank_weight of its sources)
      + w_frequency * min(1.0, (source_count - 1) / 3)
      + w_freshness * 0.5 ** (age_hours / freshness_half_life_hours)
```

Weights are `rank.weight_source`, `rank.weight_frequency`, `rank.weight_freshness`
(default 0.5 / 0.3 / 0.2) and `rank.freshness_half_life_hours` (default 12).

- An item with `published_at = None` gets a freshness term of `0`, never a guess.
- `source_count` saturates at four sources: past that, more copies say nothing new.
- After sorting, the group's `@n` cap applies, falling back to
  `report.max_per_group`.

## Edge cases

These are known before the first line of `fetch/` is written, because each one
costs an afternoon to rediscover.

| Case | What happens | What the code must do |
|------|--------------|-----------------------|
| **Reddit with the default Python User-Agent** | HTTP 403 on both `r/embedded` and `search.rss` | Always send `advanced.user_agent`; treat an empty UA as a config error |
| **Google News RSS throttling** | Repeated queries from one IP start returning empty results or HTTP 429 rather than an error page | Keep the per-host interval; treat an empty feed as a soft failure and log it instead of reporting "no news" |
| **HN Algolia returns JSON, not a feed** | A feed parser sees garbage | Dispatch on `format`, not on the response's content type |
| **Ask HN items have `url: null`** | No link to publish | Fall back to the HN item permalink built from `objectID` |
| **LWN subscriber items** | Titles arrive prefixed `[$]`, links land on a paywall | Keep them, but the prefix must survive folding so a `!` filter can exclude them if wanted |
| **VnExpress descriptions contain `<img>`** | Markup leaks into the title if description is ever used | Titles only, and strip HTML at stage 3 |
| **Diacritics in Vietnamese titles** | `Điện` never matches a keyword typed `dien` | Fold at stage 4; store the original for display |
| **A feed with no `pubDate`** | Freshness term undefined | `published_at = None`, freshness term `0`, never "now" |
| **The same story from an AMP or syndicated URL** | Two rows, two notifications | Accepted limit - canonicalisation does not resolve it, and title clustering is not implemented |
| **Google News returns its own redirector links** | Items come back as `news.google.com/rss/articles/CBMi...`, never the publisher URL, so the same story from Google News and from Hacker News does **not** collapse on `canonical_url` | Accepted limit of the same class as the AMP case. Resolving it means following each redirect - one extra request per item, against a host that already throttles |
| **The Reddit sources are unreachable on this network** | Not a 403: `www.reddit.com` fails DNS resolution (`Name or service not known`) both on the homelab host and inside the container | Failure isolation covers it - one warning line, the run keeps the other 21 sources. The User-Agent requirement above is still correct wherever Reddit does resolve |
| **An Algolia hit with an empty title** | `new_item()` raises and the hit is dropped | Counted at DEBUG per source, so a feed that suddenly ships titleless entries is visible instead of silently shrinking |
| **A source hangs** | The whole run hangs; nothing outside the process kills it | `request_timeout_s` is the only bound that exists - it must always be set |
| **Clock skew on the host** | Freshness ranking inverts | `TZ` is pinned in the container; ages are computed in UTC |
