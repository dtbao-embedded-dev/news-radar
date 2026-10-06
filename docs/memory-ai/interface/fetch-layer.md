---
title: Fetch Layer Contracts
category: interface
purpose: Every public signature of the fetch layer and the two leaf modules it stands on - what each returns, what it raises, and what it deliberately does not.
status: active
updated: 2026-10-06
source: src/news_radar/fetch/http.py, src/news_radar/fetch/feeds.py, src/news_radar/fetch/search.py, src/news_radar/item.py, src/news_radar/keywords.py
confidence: confirmed
keywords: Fetcher, HttpError, post_json, Retry-After, RETRY_AFTER_MAX, ready_in, parse, read_source, read_sources, HOST_STRIKES, host breaker, fetch schedule, collect, fixed_plan, read_fixed_feeds, build_urls, search_plan, read_search_feeds, read_all_sources, NewsItem, new_item, dedup_key, canonicalise_url, fold, strip_html, KeywordGroup, KeywordError, failure isolation, throttle
order: 5
---

# Fetch Layer Contracts

> Five modules, in dependency order: `item` and `keywords` are leaves that
> import nothing from the package; `fetch/http` is stdlib-only transport;
> `fetch/feeds` maps bodies onto items and is the **only** place a source
> failure is caught; `fetch/search` expands keyword groups into queries and
> reuses that guard.

## `item.py` - the record and its pure helpers

| Signature | Returns |
|-----------|---------|
| `NewsItem` | Frozen dataclass: `title`, `url`, `canonical_url`, `source_id`, `external_id`, `fetched_at`, `published_at=None`, `keyword_group=None` |
| `new_item(title, url, source_id, fetched_at, external_id=None, published_at=None, keyword_group=None)` | A `NewsItem`. Strips HTML from the title, derives `canonical_url`, falls back to it for `external_id`. **Raises `ValueError` on an empty title** |
| `dedup_key(item)` | `sha1(canonical_url)`, or `sha1("t:" + normalised_title)` when there is no usable URL |
| `canonicalise_url(url)` | The canonical form, or `""` for an empty URL, a hostless one, or a non-http(s) scheme |
| `fold(text)` | Lowercased, diacritics dropped, whitespace collapsed. **Punctuation kept** - matching is substring based |
| `strip_html(text)` | Tags removed, then entities decoded, then whitespace collapsed |

`fold()` special-cases `đ`/`Đ`: Unicode treats d-stroke as a letter and NFD
never decomposes it, so without the pair `Điện tử` folds to `đien tu` and a
keyword typed `dien tu` silently never matches.

`strip_html()` removes tags **before** decoding entities. Decoding first would
turn a title's literal `&lt;stdio.h&gt;` into markup and then delete it.

## `keywords.py` - the group file

| Signature | Returns |
|-----------|---------|
| `parse(path)` | `(groups, global_filter_terms)`. **Raises `KeywordError`** |
| `KeywordGroup` | `primary`, `label`, `terms`, `required`, `excluded`, `regexes` (compiled), `cap` |

`label` defaults to `primary` when the group has no `=> Label` line, and is what
a search item's `keyword_group` is set to. `KeywordError` carries `path:line`
and is raised for a group with no plain term, a non-numeric `@n`, an
unterminated or invalid `/regex/`, an unreadable file, and a file with no group
at all. A `#` starts a comment only at the start of a line, so the term
`C# programming` survives.

## `fetch/http.py` - the transport

```
Fetcher(user_agent, timeout_s=15, max_retries=2, interval_ms=2000, backoff_s=1.0)
    .get(url)               -> bytes    raises HttpError
    .post_json(url, payload, headers=None) -> bytes   raises HttpError
HttpError(message, status=None, url=None, body=b"", retry_after=None)
RETRY_AFTER_MAX = 60.0
```

**Both verbs, one code path.** `get()` reads a feed - and, since 2026-09-08,
an AI endpoint's `/v1/models` list when `summarize.py` needs a model to fall
back to - while `post_json()` talks to a notification channel or an AI
endpoint; both go through a private `_request()`, so the User-Agent, the
timeout, the retry policy and the per-host gap are decided once.
A POST is retried on the same statuses a GET is, which means a 5xx can deliver
the same message twice - the trade [[notify-channels]] already takes, where a
duplicate is the acceptable failure and a dropped story is not.

- **`headers` is merged *underneath* the transport's own, never over them.** It
  exists for one caller - `summarize.py` needs `Authorization: Bearer <key>` for
  an OpenAI-compatible endpoint, and neither channel webhook needs a header at
  all. The three the class sets for itself (User-Agent, Accept, Accept-Encoding)
  and the Content-Type overwrite whatever the caller passed, so a caller can add
  a header and can never take one away: losing the User-Agent to a typo is the
  403 on both Reddit sources, arriving from a different direction.
- **One instance per cycle.** The `{hostname: last_request}` throttle state
  lives on it, so every source in the run shares one idea of how recently a
  host was asked. Keyed by **hostname**: `hn` and `hn_algolia` are different
  hosts and do not queue behind each other; the fixed Reddit feed and the
  Reddit search are the same host and do.
- **`ready_in(host)`** returns the seconds until a host may be asked again
  (`0.0` = now) - the throttle's own arithmetic, asked without sleeping.
  `feeds.read_sources()` reads it to send whichever host is free. 🟢
- **An empty `user_agent` raises `ValueError` at construction.** That is
  Reddit's 403 with an extra step, refused where it can still be fixed.
- **Retried:** `408, 425, 429, 500, 502, 503, 504`, timeouts and connection
  errors, `max_retries` times with `backoff_s * 2**(n-1)` between attempts.
  **Not retried:** every other 4xx. A 403 answers the same however often it is
  asked.
- **A 429 is slept for exactly as long as the server asked**, not for our own
  guess: `Retry-After` first, then the JSON body's `retry_after` (Discord) or
  `parameters.retry_after` (Telegram), capped at `RETRY_AFTER_MAX = 60 s`. A
  server asking for fifteen minutes would stall a thirty-minute cycle past its
  own interval. An unparseable value - `Retry-After` may also be an HTTP-date,
  which nothing here sends - falls back to the exponential delay rather than
  earning a date parser. Google News throttles on the GET path too, so this is
  a transport rule rather than a notification one.
- **`HttpError` carries the response body.** On the notification side that
  sentence (`chat not found`, `Invalid Webhook Token`) is the fixable half of
  the failure.
- `Accept-Encoding: gzip, deflate` is sent and the response decoded by its
  `Content-Encoding` header. A body that claims an encoding it does not have is
  returned raw rather than losing the source.

## `fetch/feeds.py` - bodies into items

```
FORMATS = ("rss", "atom", "hn_algolia_json")       DEFAULT_FORMAT = "rss"

parse(body, fmt, source_id, keyword_group=None, fetched_at=None) -> list[NewsItem]
read_source(fetcher, source, keyword_group=None, fetched_at=None) -> (items, error|None)
read_sources(fetcher, plan, fetched_at=None) -> list[(items, error|None)]
collect(results) -> (items, errors)
fixed_plan(cfg) -> list[(source, None)]
read_fixed_feeds(fetcher, cfg, fetched_at=None) -> (items, errors)
HOST_STRIKES = 2
```

**`read_sources()` is the cycle's fetch scheduler.** `plan` is
`[(source, keyword_group)]`; the result is one `(items, error)` per entry, **in
plan order**, whatever order the requests went out in. 🟢

- **Send order: the busiest free host, else the soonest free.** The busiest
  host is the critical path - thirteen Google News queries cannot end sooner
  than twelve intervals after the first - so it goes whenever `ready_in()` says
  it may, and every other request fills its gaps. Ties fall to plan order. A
  fetcher without `ready_in()` (test doubles) counts as always ready.
- **Return order is plan order**, and that is load-bearing: `rank_groups()`
  sorts stably and `collapse()` keeps the first copy's title, so a list
  reordered by the transport would change which headline ships.
- **A host that fails for good is not asked again that call.** "For good" is
  the retryable class - 429, 5xx, timeout, DNS, refused - after the transport's
  own retries, `HOST_STRIKES` (2) times **in a row**; an answer in between
  resets the count. Two, not one, because one throttled query must not cost
  the other groups their results. The rest of that host's sources fail at once
  with `skipped: <host> already failed this cycle (<reason>)`, so each is still
  its own error. A 403/404 never counts - it is a verdict on one url. Without
  it a throttled Google News made each of its thirteen queries retry and wait
  up to `RETRY_AFTER_MAX`, which can stall a cycle past its interval. 🟢

- **Dispatch is on the declared format, never on the response content type.**
  `rss` and `atom` share a branch: feedparser normalises both into `entries[]`.
- `parse()` **never raises on bad content** - a truncated body, an error page,
  HTML served instead of a feed, or JSON that is not the Algolia shape all
  yield `[]`. Only an unknown `fmt` raises `ValueError`, because that is a
  config mistake and not a source having a bad day.
- `read_source()` is the **single** place a source failure is caught. It
  returns `([], (source_id, reason))` on any exception and never raises.
  `search.py` calls it too, so the guard exists once.
- **An empty parse is a soft failure**: `([], None)` plus an INFO line. Google
  News answers a throttled query with an empty feed, and calling that an error
  would redden a run for a source that is merely quiet.
- `source` is a mapping with `id`, `url` and an optional `format`.
- `errors` is a list of `(source_id, reason)` tuples.

## `fetch/search.py` - keyword groups into queries

```
KW_PLACEHOLDER = "{kw}"

build_urls(groups, templates) -> list[(url, template, group)]
search_plan(groups, cfg) -> list[(source, label)]
read_search_feeds(fetcher, cfg, groups, fetched_at=None) -> (items, errors)
read_all_sources(fetcher, cfg, groups, fetched_at=None)
    -> ((feed_items, feed_errors), (search_items, search_errors))
```

`read_all_sources()` is what `crawl()` calls: the fixed feeds and the search
plan go through **one** `read_sources()` call, so the twelve fixed feeds are
sent inside the search hosts' gaps rather than in a phase of their own, and one
host breaker covers both halves. The halves come back apart because `crawl()`
counts and logs them apart. 🟢

- `build_urls()` is **pure**: no request is made, so the request count is known
  before the first byte goes out. It is `len(groups) x len(templates)` - seven
  groups and two templates is 14 requests, on top of the eight fixed feeds.
- **A multi-word primary term is quoted as a phrase before encoding**:
  `embedded linux` travels as `%22embedded+linux%22`. Unquoted it is two words
  to a search engine and comes back as everything ever written about Linux.
- Only `{kw}` is substituted; the template's own query string (`hl=vi&gl=VN&
  ceid=VN:vi`) survives character for character.
- A template whose URL lost its `{kw}` contributes nothing and logs a warning -
  `config.validate()` rejects it first, this is the second line of defence.
- Templates are iterated **outermost** in the plan, and that is the order
  `read_search_feeds()` **returns** items in - template-major, then group.
  `rank_groups()` sorts stably and `collapse()` keeps the first copy's title,
  so this order decides tie-breaks and which headline ships. 🟢
- It is **not** the order requests are sent in - see `read_sources()` above.
  Template-major sending put every Google News query back to back and waited
  a full interval before each. Measured 2026-10-06 with the real `Fetcher`
  throttle on a fake wire (12 fixed feeds + 13 groups x 2 hosts, 60 ms latency,
  scaled to the shipped 2000 ms): the whole fetch went from **~57 s to ~28 s**
  for the same 38 requests. Two templates on one hostname (`google_news` +
  `google_news_en`) share one gap, so enabling both lengthens the critical
  path rather than overlapping. 🟢
- Items are tagged with the template id as `source_id` and the group's `label`
  as `keyword_group`. They are still matched normally in P2: the engine's idea
  of relevance does not get a free pass into the report.
- Errors are recorded per `(template, group)`: one throttled query must not
  cost the other groups their results.
