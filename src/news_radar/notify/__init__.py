"""Notification: the run's new stories, pushed to the channels that are on.

Layer 5, beside `render.py`. It reads the row shape `store.run_matches()` and
`store.day_matches()` return and turns it into messages; it decides nothing
about *which* stories go out. The diff against the seen-set, the report mode and
the secrets all live in `__main__.py` and arrive as arguments - which is why a
channel can be exercised against a local `http.server` with no config, no store
and no environment in sight.

This package imports `fetch.http` (layer 1) as well as layer 4. That widens the
layering table on purpose: a POST needs the same User-Agent, timeout, retry and
per-host gap a GET does, and honouring a 429's `Retry-After` is a transport
concern, not a per-channel one. Writing a second HTTP client here would be the
alternative.

Two things this file owns, because both channels need them and they differ only
by a number:

- **`chunk()`** - the split. A group boundary is preferred, an item boundary is
  the fallback, and a story is never cut in half.
- **`clip()`** - the cap that keeps one absurd headline from making a whole
  chunk unsendable.

Contract: docs/memory-ai/interface/notify-channels.md
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field

__all__ = ["SendResult", "chunk", "clip", "TITLE_MAX"]

log = logging.getLogger("news_radar.notify")

# The longest title that goes into a message. Long enough that no real headline
# is touched, short enough that title + link can never on their own overflow the
# smaller of the two channel budgets and cost the story its message.
TITLE_MAX = 240

# One blank line between two groups in the same message.
JOIN = "\n\n"


@dataclass
class SendResult:
    """What one channel did with one run.

    `keys` is the dedup keys of the chunks the channel **accepted**, and it is
    the only thing `mark_reported()` is ever given. A chunk that failed leaves
    its stories unreported, so the next run tries them again.
    """

    sent: int = 0
    failed: int = 0
    keys: tuple = field(default_factory=tuple)

    @property
    def stories(self):
        return len(self.keys)


def clip(text, limit=TITLE_MAX):
    """`text` shortened to `limit` characters, with an ellipsis when it was."""
    text = text or ""
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def chunk(blocks, limit):
    """`[(header, [(line, key)])]` -> `[(text, keys)]`, every text under `limit`.

    Split on a group boundary first and an item boundary second, per the channel
    contract. A single story is never split across two messages: half a headline
    with no link is worse than the same story arriving one message later.

    An empty group contributes nothing. The page prints `0 item(s)` for a
    keyword that has gone quiet because a reader is looking for exactly that;
    a message pushed to a phone is not the place to say nothing happened.
    """
    parts = []
    for header, items in blocks:
        if items:
            parts.extend(_split(header, items, limit))

    out = []
    text, keys = "", ()
    for part_text, part_keys in parts:
        candidate = part_text if not text else text + JOIN + part_text
        if text and len(candidate) > limit:
            out.append((text, keys))
            text, keys = part_text, part_keys
        else:
            text, keys = candidate, keys + part_keys

    if text:
        out.append((text, keys))
    return out


def _split(header, items, limit):
    """One group as one part, or as several parts with the header repeated.

    The header is repeated rather than dropped: a bare list of links with no
    group name is unreadable on a phone, and the second message is the one most
    likely to be read on its own.
    """
    parts, lines, keys = [], [header], ()
    for line, key in items:
        if len(lines) > 1 and len("\n".join(lines + [line])) > limit:
            parts.append(("\n".join(lines), keys))
            lines, keys = [header, line], (key,)
        else:
            lines.append(line)
            keys += (key,)

    parts.append(("\n".join(lines), keys))
    return parts
