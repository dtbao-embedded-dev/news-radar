"""Expand keyword groups into search queries, and fetch what comes back.

Layer 2. This is the half of the radar that grows without a code change:
adding a group to `frequency_words.txt` adds a hunting path, because the
group's primary term travels into the URL and the search engine does the first
cut.

Cost is `len(groups) x len(enabled templates)` requests per run - eight feeds,
six groups and three templates is 26 requests, not eight. Worth knowing before
enabling a fourth.

Wall time is a separate number from the request count. The Fetcher spaces two
requests to one host by `request_interval_ms`, so `read_all_sources()` sends
the fixed feeds and the searches as one plan through `feeds.read_sources()`:
the busiest host goes whenever it is free and every other request fills its
gaps. Thirteen groups over two hosts went from ~50 s to ~25 s at the shipped
2000 ms for the same 26 requests, and the fixed feeds now ride inside that.

Contract: docs/memory-ai/data/news-sources.md (search feeds),
docs/memory-ai/behavior/news-search.md (stage 1)
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from .feeds import collect, fixed_plan, read_sources

__all__ = ["build_urls", "search_plan", "read_search_feeds",
           "read_all_sources", "KW_PLACEHOLDER"]

log = logging.getLogger("news_radar.fetch.search")

KW_PLACEHOLDER = "{kw}"


def _query_term(term):
    """The term as the engine should receive it: a phrase if it is one.

    Unquoted, `embedded linux` is two words to a search engine and comes back
    as everything ever written about Linux. The quotes go on before encoding,
    so what travels is `%22embedded+linux%22`.
    """
    term = term.strip()
    return quote_plus('"{}"'.format(term) if " " in term else term)


def build_urls(groups, templates):
    """(url, template, group) for every group x enabled template pair.

    Pure - no request is made here. Every unknown is resolved before the first
    byte goes out, which is what makes the request count predictable.
    """
    built = []
    for template in templates:
        url_template = template.get("url") or ""
        if KW_PLACEHOLDER not in url_template:
            # config.validate() already rejects this; a template that lost its
            # placeholder would otherwise send the identical query once per
            # group and look like it was working.
            log.warning("search template %r has no %s, skipping",
                        template.get("id", "?"), KW_PLACEHOLDER)
            continue
        for group in groups:
            built.append((
                url_template.replace(KW_PLACEHOLDER, _query_term(group.primary)),
                template,
                group,
            ))
    return built


def search_plan(groups, cfg):
    """Every enabled template x group as a `feeds.read_sources()` plan entry.

    The source is tagged with the template id, and the entry with the group's
    label as its keyword group, so the report can say why a story was picked
    up. Template-major, as `build_urls()` lays it out - which is the order the
    items come back in, whatever order they were fetched in.
    """
    plan = build_urls(groups, cfg.enabled_search_templates())
    log.debug("search plan: %d request(s) from %d group(s)", len(plan), len(groups))
    return [({"id": template.get("id"), "url": url,
              "format": template.get("format")}, group.label)
            for url, template, group in plan]


def read_search_feeds(fetcher, cfg, groups, fetched_at=None):
    """Every enabled template queried with every group. Returns (items, errors).

    Search items are still matched normally in P2: the engine's idea of
    relevance does not get a free pass into the report. Errors are per
    (template, group), not per template: one throttled query must not cost the
    other nineteen groups their results.
    """
    return collect(read_sources(fetcher, search_plan(groups, cfg),
                                fetched_at=fetched_at))


def read_all_sources(fetcher, cfg, groups, fetched_at=None):
    """The cycle's whole fetch. Returns `((feed_items, feed_errors), (search_items, search_errors))`.

    One plan, not two calls, because the two halves share the per-host gap:
    twelve fixed feeds on twelve hosts cost nothing extra when they are sent
    inside the Google News gaps, and a whole extra phase when they are sent
    before them. The halves come back apart because `crawl()` counts and logs
    them apart.
    """
    fixed = fixed_plan(cfg)
    results = read_sources(fetcher, fixed + search_plan(groups, cfg),
                           fetched_at=fetched_at)
    return collect(results[:len(fixed)]), collect(results[len(fixed):])
