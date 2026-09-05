"""The Discord channel: one webhook POST per chunk, in Markdown.

Markdown, not HTML, so the escaping problem is a different one: `*_~|` and a
backtick are formatting, and a `[` or `]` in a headline ends the masked link
early and leaves a raw URL in the middle of the sentence. Both get a backslash
here, once, on the way in.

Plain `content`, no embeds. The contract calls plain content the default shape,
and the 6000-character total across embeds is easier to overrun than any
per-embed limit - a budget nothing here would gain by spending.

Contract: docs/memory-ai/interface/notify-channels.md (Discord)
"""

from __future__ import annotations

import json
import logging
import re

from . import SendResult, chunk, clip
from ..fetch.http import HttpError

__all__ = ["NAME", "LIMIT", "build", "send"]

log = logging.getLogger("news_radar.notify.discord")

NAME = "discord"

# 2000 characters, minus headroom for the same reason Telegram has it. A quarter
# of Telegram's budget means the same run makes more Discord messages than
# Telegram messages - expected, not a bug.
LIMIT = 1900

# The characters that change what a message *means* rather than how it reads.
# `(` and `)` are deliberately absent: they are only special inside the link's
# url half, which is handled by _url() instead of by escaping the title.
_MARKDOWN = re.compile(r"([\\`*_~|\[\]])")


def _e(text):
    return _MARKDOWN.sub(r"\\\1", "" if text is None else str(text))


def _url(url):
    """A url safe to sit inside `[...](...)`.

    A closing paren would end the link early and dump the rest of the address
    into the sentence. Both halves are encoded so the pair still balances for
    anything reading the raw text.
    """
    return (url or "#").replace("(", "%28").replace(")", "%29")


def _line(row):
    """One story: a bullet, the masked link, and where it came from.

    A masked link rather than a bare url on two counts - the raw address would
    widen every line past the phone's width, and Discord does not auto-embed a
    masked link, so ten stories stay ten lines instead of ten preview cards.
    The sources go in a code span because a source id may carry an underscore
    (`hn_algolia`, `r_embedded`) that italics would eat.
    """
    sources = ", ".join(row.get("sources") or ())
    return "• [{title}]({url}){sources}".format(
        title=_e(clip(row.get("title"))),
        url=_url(row.get("url") or row.get("canonical_url")),
        sources=" `{}`".format(sources) if sources else "")


def build(groups, limit=LIMIT):
    """`[(label, [row])]` -> `[(text, keys)]`, ready to post. Pure."""
    return chunk([("**{}**".format(_e(label)),
                   [(_line(row), row["dedup_key"]) for row in rows])
                  for label, rows in groups], limit)


def send(fetcher, groups, webhook_url):
    """Post every chunk to the webhook. Returns the accepted keys.

    Stops at the first refusal, like Telegram does: a 400 here is a deleted or
    revoked webhook and answers the same way for every remaining chunk.
    """
    result = SendResult()

    for text, keys in build(groups):
        try:
            fetcher.post_json(webhook_url, {"content": text})
        except HttpError as exc:
            result.failed += 1
            log.error("discord refused a message (%s): %s", exc, _why(exc.body))
            break

        result.sent += 1
        result.keys += keys

    return result


def _why(body):
    """Discord's own explanation - `Invalid Webhook Token` and friends."""
    try:
        payload = json.loads((body or b"").decode("utf-8", "replace"))
    except ValueError:
        payload = None
    if isinstance(payload, dict) and payload.get("message"):
        return payload["message"]
    return (body or b"")[:200].decode("utf-8", "replace") or "no body"
