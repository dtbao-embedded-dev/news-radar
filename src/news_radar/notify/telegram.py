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

from . import SendResult, UTC, chunk, clip, stamp
from ..fetch.http import HttpError

__all__ = ["NAME", "LIMIT", "build", "send", "alert"]

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


def _line(row, tz):
    """One story: the linked title, the AI sentence under it, then the time.

    The same three things the page shows, in the same order, because a reader
    comparing the two should be comparing one report with itself. The source
    ids used to sit where the time is; they left the page in v0.2.1 and left
    the message with it.

    A story with no summary collapses back to the **one-line** shape this
    channel had before, time and all on the title's line - which is every story
    when `ai.enabled` is false. The time only moves to its own line when there
    is a sentence between them to move it, because a bare title and a bare
    timestamp on two lines is a taller message saying exactly as much.
    """
    head = '• <a href="{url}">{title}</a>'.format(
        url=_e(row.get("url") or row.get("canonical_url") or "#"),
        title=_e(clip(row.get("title"))))
    when = "<i>{}</i>".format(_e(stamp(row.get("published_at"), tz)))

    gist = (row.get("ai_summary") or "").strip()
    if not gist:
        return "{} {}".format(head, when)
    return '{}\n<i>“{}”</i>\n{}'.format(head, _e(gist), when)


def build(groups, tz=UTC, limit=LIMIT):
    """`[(label, [row])]` -> `[(text, keys)]`, ready to post.

    Pure: no network, no clock, no config - `tz` is the display zone the caller
    read out of `app.timezone`, and it defaults to UTC so this stays callable
    with nothing configured at all. Every escaping and splitting rule this
    channel has is decided here and can be checked without a socket.
    """
    return chunk([("<b>{}</b>".format(_e(label)),
                   [(_line(row, tz), row["dedup_key"]) for row in rows])
                  for label, rows in groups], limit)


def send(fetcher, groups, token, chat_id, tz=UTC):
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

    for text, keys in build(groups, tz):
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


def alert(fetcher, text, token, chat_id):
    """One operational message. Returns True if Telegram took it.

    **No `parse_mode`, and therefore no escaping.** `send()` needs HTML because
    a story is a link; an alert is a sentence, and the only thing HTML mode
    could add here is a way for a stray `<` in an exception message to cost the
    whole alert. The one message you must not lose is the one saying something
    is broken.
    """
    try:
        fetcher.post_json(API.format(token=token), {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        })
    except HttpError as exc:
        log.error("telegram refused the alert (%s): %s", exc, _why(exc.body))
        return False
    return True


def _why(body):
    """Telegram's own explanation, which is the fixable half of the failure."""
    try:
        payload = json.loads((body or b"").decode("utf-8", "replace"))
    except ValueError:
        payload = None
    if isinstance(payload, dict) and payload.get("description"):
        return payload["description"]
    return (body or b"")[:200].decode("utf-8", "replace") or "no body"
