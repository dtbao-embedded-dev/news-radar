---
title: Fetch Layer Contracts
category: interface
purpose: Every public signature of the fetch layer and the two leaf modules it stands on - what each returns, what it raises, and what it deliberately does not.
status: active
updated: 2026-09-05
source: src/news_radar/fetch/http.py, src/news_radar/fetch/feeds.py, src/news_radar/fetch/search.py, src/news_radar/item.py, src/news_radar/keywords.py
confidence: confirmed
keywords: Fetcher, HttpError, post_json, Retry-After, RETRY_AFTER_MAX, parse, read_source, read_fixed_feeds, build_urls, read_search_feeds, NewsItem, new_item, dedup_key, canonicalise_url, fold, strip_html, KeywordGroup, KeywordError, failure isolation, throttle
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
    .post_json(url, payload) -> bytes   raises HttpError
HttpError(message, status=None, url=None, body=b"", retry_after=None)
RETRY_AFTER_MAX = 60.0
```

**Both verbs, one code path.** `get()` reads a feed and `post_json()` talks to a
notification channel; both go through a private `_request()`, so the
User-Agent, the timeout, the retry policy and the per-host gap are decided once.
A POST is retried on the same statuses a GET is, which means a 5xx can deliver
the same message twice - the trade [[notify-channels]] already takes, where a
duplicate is the acceptable failure and a dropped story is not.

- **One instance per cycle.** The `{hostname: last_request}` throttle state
  lives on it, so every source in the run shares one idea of how recently a
  host was asked. Keyed by **hostname**: `hn` and `hn_algolia` are different
  hosts and do not queue behind each other; the fixed Reddit feed and the
  Reddit search are the same host and do.
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
read_fixed_feeds(fetcher, cfg, fetched_at=None) -> (items, errors)
```

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
read_search_feeds(fetcher, cfg, groups, fetched_at=None) -> (items, errors)
```

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
- Templates are iterated **outermost**, so a run's requests arrive grouped by
  host, which is what the per-host throttle is for.
- Items are tagged with the template id as `source_id` and the group's `label`
  as `keyword_group`. They are still matched normally in P2: the engine's idea
  of relevance does not get a free pass into the report.
- Errors are recorded per `(template, group)`: one throttled query must not
  cost the other groups their results.
