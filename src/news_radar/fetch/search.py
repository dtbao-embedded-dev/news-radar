"""Expand keyword groups into search queries, and fetch what comes back.

Layer 2. This is the half of the radar that grows without a code change:
adding a group to `frequency_words.txt` adds a hunting path, because the
group's primary term travels into the URL and the search engine does the first
cut.

Cost is `len(groups) x len(enabled templates)` requests per run - eight feeds,
seven groups and two templates is 22 requests, not eight. Worth knowing before
enabling a third template.

Contract: docs/memory-ai/data/news-sources.md (search feeds),
docs/memory-ai/behavior/news-search.md (stage 1)
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from .feeds import read_source

__all__ = ["build_urls", "read_search_feeds", "KW_PLACEHOLDER"]

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


def read_search_feeds(fetcher, cfg, groups, fetched_at=None):
    """Every enabled template queried with every group. Returns (items, errors).

    Items are tagged with the template id as their source and the group's label
    as their keyword group, so the report can say why a story was picked up.
    They are still matched normally in P2: the engine's idea of relevance does
    not get a free pass into the report.
    """
    items = []
    errors = []
    plan = build_urls(groups, cfg.enabled_search_templates())
    log.debug("search plan: %d request(s) from %d group(s)", len(plan), len(groups))

    for url, template, group in plan:
        source = {"id": template.get("id"), "url": url,
                  "format": template.get("format")}
        got, error = read_source(fetcher, source, keyword_group=group.label,
                                 fetched_at=fetched_at)
        items.extend(got)
        if error:
            # Per (template, group), not per template: one throttled query must
            # not cost the other nineteen groups their results.
            errors.append(error)
    return items, errors
