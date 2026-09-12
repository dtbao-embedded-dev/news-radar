---
title: News Sources and Search Paths
category: data
purpose: Every source news-radar pulls from - the fixed feed list, the keyword-driven search URL templates, and what each one returns.
status: active
updated: 2026-09-12
source: config/config.yaml.example, src/news_radar/fetch/feeds.py, src/news_radar/fetch/search.py
confidence: confirmed
keywords: sources, feeds, RSS, Atom, match_excerpt, gh_trending, openai, huggingface, esp_idf_releases, cnx_esp32, hnrss, lobste.rs, hackaday, lwn, reddit, vnexpress, genk, tinhte, google news rss, hn algolia, search url, user-agent
order: 1
---

# News Sources and Search Paths

> Two kinds of source feed the same pipeline. **Fixed feeds** are fetched whole
> every run and filtered locally. **Search feeds** are built at runtime from each
> keyword group, so the keyword travels into the URL and the source does the
> first cut.

## Fixed feeds

Fetched in full on every run, then matched against `frequency_words.txt`. Adding
one is a config edit, never a code edit.

| id | Name | URL | Format | Language | Notes |
|----|------|-----|--------|----------|-------|
| `hn` | Hacker News front page | `https://hnrss.org/frontpage` | RSS 2.0 | en | Third-party bridge over HN; item `comments` link differs from the story link |
| `lobsters` | Lobsters | `https://lobste.rs/rss` | RSS 2.0 | en | Tags live in the title suffix, not a separate field |
| `hackaday` | Hackaday | `https://hackaday.com/blog/feed/` | RSS 2.0 | en | WordPress feed; full body in `content:encoded` - ignore it, titles only |
| `lwn` | LWN headlines | `https://lwn.net/headlines/rss` | RSS 2.0 | en | Subscriber-only items appear with a `[$]` title prefix |
| `r_embedded` | r/embedded | `https://www.reddit.com/r/embedded/.rss` | Atom | en | **Requires a real User-Agent**; the default Python one gets HTTP 403. **Needs its own resolver**: `www.reddit.com` failed to resolve on this homelab - host *and* container - so the crawl service sets `dns: [1.1.1.1, 8.8.8.8]` in `docker-compose.yml`. `reddit.com` resolves and then 301s to the name that will not; `old.reddit.com` resolves and then serves 350 kB of HTML rather than the feed. Neither is a workaround, the resolver is |
| `vnexpress_sohoa` | VnExpress So hoa | `https://vnexpress.net/rss/so-hoa.rss` | RSS 2.0 | vi | Description carries an `<img>` tag - strip HTML before matching |
| `genk` | GenK | `https://genk.vn/rss/home.rss` | RSS 2.0 | vi | Mixed tech and consumer news |
| `tinhte` | Tinh te | `https://tinhte.vn/rss` | RSS 2.0 | vi | Forum-flavoured; heavier duplicate rate than the others |
| `gh_trending` | GitHub Trending | `https://mshibanami.github.io/GitHubTrendingRSS/daily/all.xml` | RSS 2.0 | en | Third-party mirror - GitHub publishes no trending feed. **The only source with `match_excerpt: true`**: every entry is titled `owner/repo` and the description is the only matchable text (1 of 18 matched on the title, 10 with the excerpt). Carries **no dates at all**, so its freshness term is always 0 and `rank_weight` is its whole score. Its own `GitHub Trending` keyword group is what keeps it out of the AI group's way |
| `openai` | OpenAI News | `https://openai.com/news/rss.xml` | RSS 2.0 | en | The full archive, ~1,170 entries every fetch, ~700 kB. A primary source: weighted 1.0 |
| `huggingface` | Hugging Face Blog | `https://huggingface.co/blog/feed.xml` | RSS 2.0 | en | ~860 entries every fetch. **Carries no descriptions at all**, so `match_excerpt` would be inert here even if set |
| `esp_idf_releases` | ESP-IDF Releases | `https://github.com/espressif/esp-idf/releases.atom` | Atom | en | Always the same ten releases, old point releases included, and none of them ages out. At a 12 h half-life anything older than ~2 days scores 0 for freshness, so all ten score identically - weight 1.0 put ten of them in the ESP32 group's twelve slots. Weighted 0.8, only a genuinely fresh release clears the cut, which is the wanted behaviour and means the source shows nothing on a quiet week |
| `cnx_esp32` | CNX Software (ESP32) | `https://www.cnx-software.com/tag/esp32/feed/` | RSS 2.0 | en | Already narrowed by the source's own tag: 27 of 32 entries matched a shipped group on 2026-09-07 |

Each entry in `config.yaml` carries an `id`, a `name`, a `url`, `enabled`, and an
optional `rank_weight` (default `1.0`) that feeds the ranking in
[[news-search]].

## Search feeds

For every keyword group in `frequency_words.txt`, the group's **primary term**
(the first line of the group) is substituted into each enabled template. One
group with three templates enabled produces three requests per run.

| id | Template | Returns | Substitution |
|----|----------|---------|--------------|
| `google_news` | `https://news.google.com/rss/search?q={kw}+when:1d&hl=vi&gl=VN&ceid=VN:vi` | RSS 2.0 | **Ships disabled since the keyword file reached eleven groups** (thirteen since 2026-09-12) - see the row below. `{kw}` percent-encoded; a multi-word term is wrapped in `%22...%22` to search the phrase. `when:1d` is not optional - without it the engine answers relevance-first and returns hits aged months. It was `when:7d` until 2026-09-12: a week is not a radar, and this template was the one carrying the same story back three and four days running |
| `google_news_en` | the same url with `hl=en&gl=US&ceid=US:en` | RSS 2.0 | Not a duplicate: the locale decides which press is searched. Measured 2026-09-05 over the six shipped groups, `hl=vi` returned 48 usable stories and **all of them were the AI group** - the Vietnamese press does not cover ESP32, RTOS or RISC-V; `hl=en` returned 218 across all six. A template costs one request **per keyword group**, so at thirteen groups `hl=vi` would spend thirteen requests a cycle at the host most likely to throttle, for coverage the five model groups replace - it is switched off, and `vnexpress_sohoa` and `tinhte` still carry Vietnamese tech news |
| `hn_algolia` | `https://hn.algolia.com/api/v1/search_by_date?query={kw}&tags=story&typoTolerance=false` | **JSON**, not a feed | `{kw}` percent-encoded; read `hits[]`, fields `title`, `url`, `created_at`, `objectID`. `search_by_date` orders chronologically, so the window needs no epoch computing; `tags=story` drops comment hits, whose title is not a headline. **`typoTolerance=false` is required, not cosmetic**: with it on, Algolia matches 41,612 stories for `RTOS` and `FreeToken` for `FreeRTOS`, and a date sort then returns the most recent of that noise - `RTOS` yielded 0 usable of 20. Off, it is strictly better on every shipped group: 97 usable a cycle instead of 77 |
| `reddit_search` | `https://www.reddit.com/search.rss?q={kw}&sort=new` | Atom | `{kw}` percent-encoded; same User-Agent requirement, and the same resolver requirement |

`hl` / `gl` / `ceid` on the Google template pin the result locale to Vietnamese.
Changing them to `hl=en&gl=US&ceid=US:en` gives the English-language cut of the
same query; both may be enabled at once as two separate template entries.

An item from a search feed is tagged with **both** the template id and the keyword
group that produced it, so the report can say why a story was picked up.

## Field mapping

Every source is normalised into the shape in [[news-item]] before anything else
touches it.

| NewsItem field | RSS 2.0 | Atom | HN Algolia JSON |
|----------------|---------|------|-----------------|
| `title` | `item/title` | `entry/title` | `hits[].title` |
| `url` | `item/link` | `entry/link[@rel="alternate"]/@href` | `hits[].url` (may be null for Ask HN - fall back to the item permalink) |
| `published_at` | `item/pubDate` (RFC 822) | `entry/published` or `entry/updated` (RFC 3339) | `hits[].created_at` (RFC 3339) |
| `source_id` | the config `id` | the config `id` | `hn_algolia` |
| `external_id` | `item/guid` if present, else the link | `entry/id` | `hits[].objectID` |

A missing `published_at` is recorded as `None`, never as "now" - freshness ranking
must be able to tell "no date" from "just published".

## Politeness and limits

| Source | Constraint | Consequence for the fetcher |
|--------|-----------|-----------------------------|
| Reddit (both entries) | Blocks the default Python User-Agent with HTTP 403 | Send an identifying UA such as `news-radar/<version> (+https://news.dtbao.org)` |
| Google News RSS | Throttles repeated queries from one IP; no documented quota | Keep the per-host interval at 2 s or more; a run with 20 keyword groups is 20 requests |
| HN Algolia | Documented ~10 000 requests/hour per IP | Not a practical limit here |
| All | No API keys anywhere | Nothing to store in `.env` for fetching; secrets are notification-only |

The per-host minimum interval is a single config value
(`advanced.request_interval_ms`, default 2000) applied by hostname, not by source
id - `hn` and `hn_algolia` are different hosts, the two Reddit entries are not.

## Adding a source later

1. Add an entry under `feeds:` (fixed) or `search_templates:` (search) in
   `config/config.yaml`.
2. If it returns something that is neither RSS, Atom, nor a JSON shape already
   handled, it needs a parser in `fetch/` - that is a code change and a new task.
3. Record it in the table above and restamp `updated`.
