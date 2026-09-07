---
title: How News Is Searched, Matched and Ranked
category: behavior
purpose: The end-to-end crawl algorithm - which URLs are built, how a title is matched against a keyword group, how duplicates collapse, and how the shortlist is ordered.
status: active
updated: 2026-09-07
source: src/news_radar/fetch/, src/news_radar/filter.py, src/news_radar/rank.py, src/news_radar/__main__.py
confidence: confirmed
keywords: crawl, search algorithm, matching, max_age_days, fresh_enough, age cut, match_excerpt, excerpt, _haystack, diacritics, dedup, ranking, freshness, half-life, user-agent, 403, rate limit, edge cases
order: 1
---

# How News Is Searched, Matched and Ranked

> One run is six stages: build the URL list, fetch, normalise, match, collapse,
> rank. Every stage is pure except fetch, which is the only one that can fail
> partially - and it must fail partially rather than abort.

## Stage 1 - build the URL list

1. Read every `feeds[]` entry with `enabled: true`. Each contributes one URL.
2. Parse `frequency_words.txt` into groups. Take each group's **primary term**
   - its first plain term, or its `=> Label` when the group is regex-only -
   (its first plain line), skipping `[GLOBAL_FILTER]`.
3. For every enabled `search_templates[]` entry, substitute each primary term into
   `{kw}`, percent-encoded. A multi-word term is wrapped in quotes first so the
   search engine treats it as a phrase.
4. The result is one flat list of `(url, source_id, keyword_group | None)`.

Cost is predictable and worth stating out loud: `len(feeds) + len(groups) x
len(enabled templates)`. Measured on the shipped config: thirteen feeds, seven
groups and three enabled templates is **34 requests and ~59 s per run**, not
thirteen requests. Adding a keyword group therefore costs one request per
enabled template, every cycle - the `GitHub Trending` group's three are spent
on queries whose answers its own regex then discards. `build_urls()` is pure, so that number is known before the first
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

**Which text is matched is a property of the source.** By default it is the
title alone. A source carrying `match_excerpt: true` is matched on
`title + newline + excerpt` instead - all four rules above, the regexes
included. `__main__._excerpt_sources()` collects those ids and hands the set to
`select()`; `filter._haystack()` does the joining.

It is opt-in, and the measurement is why. Reading the excerpt for **every**
source was tried on 2026-09-07 across twelve live sources: 1031 matches became
1460, and the extras were stories that mention a keyword once in the body -
`An Alien Mind` from Hacker News, `Kernel prepatch 7.3-rc2` from LWN. One source
needs it: GitHub trending titles every entry `owner/repo`, so title-only
matching passed 1 of 18 entries and the excerpt passed 10.

Two consequences worth knowing before setting the flag:

- **The exclusions widen with it.** A `!` term and `[GLOBAL_FILTER]` read the
  same joined text, or noise admitted through the excerpt could not be filtered
  back out.
- **An anchored regex needs a lookahead, not `$`.** The regex is shown the
  joined text, so `/^owner/repo$/` matches the title alone and nothing once a
  description follows it. The shipped `GitHub Trending` group ends
  `(?=\n|$)` for exactly this reason - a `$` cost it every one of its
  entries the first time it ran.

Matching is done on a folded form of the title: lowercased, Unicode NFD, combining
marks removed, whitespace collapsed. So `Điện tử` matches `dien tu`, and `ESP32`
matches `esp32`. `/regex/` lines are applied to the **original** title, not the
folded one, because a regex author is entitled to write their own case rules.

**A regex can only widen a group, never narrow it**, because step 2 above is an
any-of across plain terms *and* regexes. That is worth knowing before reaching
for one to fix a false positive: it will not.

The way to narrow a group is therefore to give it **no plain term** and let its
regexes be the whole of its matching, taking the search query from `=> Label`
instead. The shipped `RTOS` group is the worked example. Folding is what forces
it: `fold("RTOs") == fold("RTOS") == "rtos"`, so a plain term cannot separate an
RTOS story from an Indian Regional Transport Office, and 4 of that group's 10
stories were e-rickshaw enforcement and licence backlogs on 2026-09-07.
`/\bRTOS\b/` on the original title separates them exactly - measured 0 of 3
noise kept, 4 of 4 real stories kept - and the query stays the short `RTOS`
that `typoTolerance=false` made work in the first place.

An item may belong to several groups. It is counted once per group it matches,
and `select()` returns its labels in the keyword file's own group order.

Signatures are in [[selection-layer]].

A search-feed item carries the group whose term produced its query, but it is
**still matched normally** - the search engine's idea of relevance does not get a
free pass into the report.

## Stage 5 - collapse

Items are grouped by `dedup_key` ([[news-item]]). The survivor keeps the earliest
`published_at`, the union of `source_id`s and the union of the labels stage 4
gave each copy - it is displayed with the first copy's title and link, but dated
by the earliest fact any source had. The size of that union is the
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

**The age cut runs first.** `rank.max_age_days` drops a story past the limit
**before** anything is scored - `fresh_enough()` decides one story at a time.
It is the floor the score cannot express: freshness reaches 0 after about two
days, so past that a three-day-old story and a three-year-old one are the same
number, and a group short of fresh matches fills the rest of its cap from
whatever archive a feed ships. Measured before the cut existed: 12 of 68
shortlisted stories were over 30 days old, five of them Hugging Face posts
taking half of `AI Repos`, the oldest **27,466 hours**.

Two properties decided by measurement rather than taste:

- **An undated story is kept, at every threshold.** The same rule as the
  freshness term below, from the other end: a missing date is not evidence.
  Dropping them would also empty the shipped `GitHub Trending` group, whose
  feed dates none of its entries.
- **Groups refill; they do not shrink.** The cut applies to the whole pool
  before any group is filled. Measured on a real cycle at 14 days: the oldest
  stored story went from 27,466 h to 284 h, nothing over 336 h survived, and
  six of the seven groups stayed at their caps. Only `RTOS` shrank, 8 to 4,
  because four of its eight really were over a fortnight old - which is the
  section going quiet, the signal this report is built to show.

- An item with `published_at = None` gets a freshness term of `0`, never a guess.
- An item dated in the **future** is clamped to age `0` rather than trusted:
  `0.5 ** negative` is greater than 1, so one bad `pubDate` would outrank every
  real story.
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
| **Reddit is unreachable from some networks** | Not a 403: `www.reddit.com` fails DNS resolution (`Name or service not known`). It is a property of the network, not of the deployment - on 2026-09-07 `r_embedded` returned **25 items on the homelab** while failing to resolve from a Windows workstation on a different network | Failure isolation covers it - one warning line, the run keeps every other source. Do not disable the feed on the strength of one machine's result, and the User-Agent requirement above still holds wherever Reddit does resolve |
| **An Algolia hit with an empty title** | `new_item()` raises and the hit is dropped | Counted at DEBUG per source, so a feed that suddenly ships titleless entries is visible instead of silently shrinking |
| **A source hangs** | The whole run hangs; nothing outside the process kills it | `request_timeout_s` is the only bound that exists - it must always be set |
| **Clock skew on the host** | Freshness ranking inverts | `TZ` is pinned in the container; ages are computed in UTC |
| **A feed dates an item in the future** | `0.5 ** (negative / half_life)` exceeds 1 and that one item tops every group it is in | `score()` clamps the age at `0`, so a future timestamp is worth exactly as much as "published now" and no more |
| **The search templates answer relevance-first, not date-first** | Measured 2026-09-05: Google News returned hits aged 1704-5783 h for `ESP32`, HN Algolia the same shape. At a 12 h half-life the freshness term is `0` for nearly every search hit, so the shortlist ranks on source weight alone and ties are broken by fetch order | Not a code defect - the fix is narrowing both queries to a recent window in `config.yaml`. Until then, expect the search half of the report to be relevance-ordered, not fresh |
| **`rank.py` cannot read the config** | The per-source `rank_weight` is in `config.yaml`, which layer 3 may not import | `__main__._source_weights(cfg)` builds `{source_id: rank_weight}` and passes it in; an unknown id scores the neutral `1.0` |
