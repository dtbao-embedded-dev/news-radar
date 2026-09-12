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
    "NewsItem", "new_item", "dedup_key", "key_for_title", "title_key",
    "canonicalise_url", "strip_html", "fold", "EXCERPT_MAX",
]

# How much of a feed's own description survives into the store. Feeds are wildly
# inconsistent here - a one-line teaser from one, the entire article from the
# next - and the only consumer is a prompt, where the whole article would be
# paid for and then ignored. Six hundred characters is a couple of paragraphs:
# enough for a model to say what the piece is about, bounded enough that fifty
# of them still fit in one request.
EXCERPT_MAX = 600

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

# A publisher's name tacked onto the end of a headline. Google News does it to
# every entry it carries - `Anthropic says ... - Bloomberg` - so the same
# article arrives with a byline from the aggregator and without one from the
# publisher's own feed, and the two must still be one story.
_PUBLISHER_SUFFIX = re.compile(r"\s+[-|–—]\s+[^-|–—]{2,40}$")

# Below this many words the remainder is not a headline any more. `ESP32-C6
# ships - Hackaday` would be cut to two words, and at that length a dash is as
# likely to be part of the title as it is to be a byline - so the suffix stays
# and the two spellings keep separate keys.
_SUFFIX_MIN_WORDS = 5


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
    # The feed's own description, stripped and capped - what the AI summary is
    # written from. Empty is the normal case for a source that carries none;
    # nothing downstream may require it.
    excerpt: str = ""


def new_item(title, url, source_id, fetched_at,
             external_id=None, published_at=None, keyword_group=None,
             excerpt=None):
    """Build a NewsItem, deriving what the parsers should not have to derive.

    Raises ValueError on an empty title: an item nobody can read is not a story,
    and dropping it here means no later stage has to check.
    """
    title = strip_html(title)
    if not title:
        raise ValueError("item has no title (source_id={!r}, url={!r})".format(
            source_id, url))

    # Same treatment the title gets, and for the same reason: a description
    # arrives as markup from a stranger's CMS, and every consumer downstream
    # (the store, the prompt, the page) wants text. Capped after stripping, so
    # the cap counts characters a reader would see rather than tags.
    excerpt = strip_html(excerpt)[:EXCERPT_MAX].strip()

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
        excerpt=excerpt,
    )


def title_key(title):
    """The comparison form of a headline: folded, de-bylined, de-punctuated.

    Punctuation goes here and not in `fold()`, which keeps it on purpose so a
    keyword typed `ESP32-S3` can still match. Identity wants the opposite: two
    sources that disagree only about a colon are carrying one story.
    """
    folded = fold(title)
    trimmed = _PUBLISHER_SUFFIX.sub("", folded)
    if len(trimmed.split()) >= _SUFFIX_MIN_WORDS:
        folded = trimmed
    return _SPACE.sub(" ", _PUNCT.sub(" ", folded)).strip()


def key_for_title(title):
    """`title_key()` as the digest the store is keyed by.

    Takes a headline rather than a `NewsItem` so `store.open_db()` can recompute
    the key of a row it is migrating, where there is no item to build.
    """
    return hashlib.sha1(("t:" + title_key(title)).encode("utf-8")).hexdigest()


def dedup_key(item):
    """What collapses the same story arriving from several sources.

    **The headline is the identity; the URL is not.** A URL looks like the
    stronger key and is not one: Google News answers the same article with a
    different opaque `news.google.com/rss/articles/CBMi...` redirect on every
    query, so a url-keyed store held one story under as many as nine keys, and
    a phone got nine messages. Measured 2026-09-12 over 1266 live items: 121 of
    them (9.6%) were duplicates of another row, in 84 groups, and not one of
    those groups mixed two different stories.

    Keying on the headline also collapses what no URL rule could - the same
    piece from `cnx-software.com` and from Google News' copy of it, or a
    Bloomberg story on Hacker News and the same one carrying its byline.

    The known ceiling: two genuinely different articles with a byte-identical
    normalised headline become one story. None was found in those 1266 items,
    and real recurring columns carry a date or a version in the title
    (`Kernel prepatch 7.3-rc2`), which keeps them apart.
    """
    # ponytail: exact-match on the normalised title. Near-duplicate headlines
    # from two outlets still make two stories; clustering them needs a
    # similarity pass, which cannot be a hash and is not worth it until the
    # exact case stops being the bulk of the noise.
    return key_for_title(item.title)
