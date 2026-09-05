"""The Telegram channel: one `sendMessage` per chunk, in Telegram's own HTML.

`parse_mode: HTML` rather than Markdown, because Telegram's Markdown refuses a
message over any unbalanced `*` or `_` in a headline and the story is lost.
HTML has one escaping rule, `&` `<` `>`, applied here to everything that came
off a feed - and every title, link and source id did.

Contract: docs/memory-ai/interface/notify-channels.md (Telegram)
"""

from __future__ import annotations

import html
import json
import logging

from . import SendResult, chunk, clip
from ..fetch.http import HttpError

__all__ = ["NAME", "LIMIT", "build", "send"]

log = logging.getLogger("news_radar.notify.telegram")

NAME = "telegram"

# Module level so a test can point it at a local http.server.
API = "https://api.telegram.org/bot{token}/sendMessage"

# Telegram's hard limit is 4096 **UTF-16 code units**, which is not what len()
# counts: an emoji in a headline is one Python character and two of Telegram's.
# The headroom is cheaper than carrying a UTF-16 counter for a limit no real
# run gets near.
LIMIT = 4000


def _e(text):
    return html.escape("" if text is None else str(text), quote=True)


def _line(row):
    """One story: a bullet, the linked title, and where it came from."""
    sources = ", ".join(row.get("sources") or ())
    return '• <a href="{url}">{title}</a>{sources}'.format(
        url=_e(row.get("url") or row.get("canonical_url") or "#"),
        title=_e(clip(row.get("title"))),
        sources=" <i>{}</i>".format(_e(sources)) if sources else "")


def build(groups, limit=LIMIT):
    """`[(label, [row])]` -> `[(text, keys)]`, ready to post.

    Pure: no network, no clock, no config. Every escaping and splitting rule
    this channel has is decided here and can be checked without a socket.
    """
    return chunk([("<b>{}</b>".format(_e(label)),
                   [(_line(row), row["dedup_key"]) for row in rows])
                  for label, rows in groups], limit)


def send(fetcher, groups, token, chat_id):
    """Post every chunk. Returns a SendResult carrying the accepted keys.

    The first refusal ends the channel for this run. A 400 is a bad token, a bad
    chat id or a message Telegram could not parse, and it answers the same way
    for chunk two as for chunk one; a 429 that survived the transport's own
    retry means the bot is throttled, and hammering it is how throttled becomes
    banned. Whatever was accepted before the refusal still counts as sent, so
    those stories are not re-pushed tomorrow.
    """
    url = API.format(token=token)
    result = SendResult()

    for text, keys in build(groups):
        try:
            fetcher.post_json(url, {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                # One preview per message would bury the list under a single
                # story's thumbnail.
                "disable_web_page_preview": True,
            })
        except HttpError as exc:
            result.failed += 1
            log.error("telegram refused a message (%s): %s", exc, _why(exc.body))
            break

        result.sent += 1
        result.keys += keys

    return result


def _why(body):
    """Telegram's own explanation, which is the fixable half of the failure."""
    try:
        payload = json.loads((body or b"").decode("utf-8", "replace"))
    except ValueError:
        payload = None
    if isinstance(payload, dict) and payload.get("description"):
        return payload["description"]
    return (body or b"")[:200].decode("utf-8", "replace") or "no body"
