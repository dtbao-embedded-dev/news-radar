"""The record every story is normalised into, and the pure helpers around it.

A leaf module: standard library only, no import from the rest of the package.
Everything downstream - filter, rank, store, render, notify - reads `NewsItem`
and nothing earlier, so this file is the one place the shape is defined.

Contract: docs/memory-ai/data/news-item.md
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

__all__ = [
    "NewsItem", "new_item", "dedup_key", "canonicalise_url", "strip_html", "fold",
]

_TAG = re.compile(r"<[^>]*>")
_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)

# Tracking parameters dropped during canonicalisation. Anything starting `utm_`
# goes too - the list of utm_* suffixes is open-ended and every one of them is
# noise that would otherwise split one story into several dedup keys.
_DROP_PARAMS = frozenset(
    ("fbclid", "gclid", "ref", "ref_src", "spm", "s_cid"))

# NFD decomposes every Vietnamese vowel into letter + combining mark, so the
# marks can be dropped in one pass - except d-stroke, which Unicode treats as a
# letter of its own and never decomposes. Without this pair, "Điện tử" folds to
# "dien tu" for the vowels and stays "đien tu" for the consonant, and a keyword
# typed "dien tu" silently never matches.
_D_STROKE = str.maketrans({"đ": "d", "Đ": "d"})


def strip_html(text):
    """Tags out, entities in, whitespace collapsed. Titles only, once, here.

    Tags are removed before entities are decoded: `&lt;b&gt;` in a title is text
    the author wrote, not markup, and decoding first would delete it.
    """
    if not text:
        return ""
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", text))).strip()


def fold(text):
    """The comparison form: lowercased, diacritics dropped, whitespace collapsed.

    Punctuation is deliberately kept - matching is substring based, and folding
    `ESP32-S3` into `esp32 s3` would stop the keyword `ESP32-S3` matching it.
    """
    if not text:
        return ""
    lowered = text.lower().translate(_D_STROKE)
    decomposed = unicodedata.normalize("NFD", lowered)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _SPACE.sub(" ", stripped).strip()


def canonicalise_url(url):
    """The dedup input: one URL spelling per story, or "" if there is none.

    Steps, in the order docs/memory-ai/data/news-item.md fixes them: lowercase
    scheme and host, drop a leading `www.`, force https, drop tracking
    parameters, drop the fragment, strip a trailing slash unless the path is
    exactly `/`. Every other query parameter survives - some sites carry the
    article id there, and dropping it would collapse two different stories.
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""

    if parts.scheme.lower() not in ("http", "https", ""):
        # mailto:, magnet:, javascript: - nothing downstream can open it, and a
        # story is not reachable through it. Treated as "no usable URL", which
        # sends dedup to its title fallback.
        return ""

    host = parts.hostname or ""
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    if parts.port:
        host = "{}:{}".format(host, parts.port)

    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
         if not k.lower().startswith("utm_") and k.lower() not in _DROP_PARAMS])

    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"

    return urlunsplit(("https", host, path, query, ""))


@dataclass(frozen=True)
class NewsItem:
    """One story, as fetched. Immutable: later stages wrap it, never mutate it."""

    title: str
    url: str
    canonical_url: str
    source_id: str
    external_id: str
    fetched_at: dt.datetime
    published_at: dt.datetime | None = None
    keyword_group: str | None = None


def new_item(title, url, source_id, fetched_at,
             external_id=None, published_at=None, keyword_group=None):
    """Build a NewsItem, deriving what the parsers should not have to derive.

    Raises ValueError on an empty title: an item nobody can read is not a story,
    and dropping it here means no later stage has to check.
    """
    title = strip_html(title)
    if not title:
        raise ValueError("item has no title (source_id={!r}, url={!r})".format(
            source_id, url))

    canonical = canonicalise_url(url)
    return NewsItem(
        title=title,
        url=(url or "").strip(),
        canonical_url=canonical,
        source_id=source_id,
        # The source's own id when it gave one, else the canonical URL. The
        # title is not a fallback here: two sources publishing the same story
        # must keep distinct external ids, which dedup then collapses.
        external_id=external_id or canonical,
        fetched_at=fetched_at,
        published_at=published_at,
        keyword_group=keyword_group,
    )


def dedup_key(item):
    """What collapses the same story arriving from several sources.

    The URL is the key whenever there is one. The title fallback exists because
    aggregator items sometimes carry only a permalink to the aggregator itself,
    and two of those would otherwise never meet.
    """
    if item.canonical_url:
        return hashlib.sha1(item.canonical_url.encode("utf-8")).hexdigest()
    normalised = _SPACE.sub(" ", _PUNCT.sub(" ", fold(item.title))).strip()
    return hashlib.sha1(("t:" + normalised).encode("utf-8")).hexdigest()
