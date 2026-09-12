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

Four things this file owns, because both channels need them and they differ
only by a number:

- **`pick()`** - the group order and the seen-set diff, applied to the store's
  rows before either channel sees them.
- **`messages()`** - one message per story, header and all. A story too long
  for the channel is clipped, never split across two messages.
- **`clip()`** - the cap that keeps one absurd headline or a runaway AI
  sentence from making a message unsendable.
- **`stamp()`** - the published time, spelled the way the page spells it.

Contract: docs/memory-ai/interface/notify-channels.md
"""

from __future__ import annotations

import datetime as dt
import logging

from dataclasses import dataclass, field

__all__ = ["SendResult", "pick", "messages", "clip", "stamp", "TITLE_MAX",
           "TIME_FMT", "NO_TIME", "UTC", "NOTIFY_INTERVAL_MS"]

log = logging.getLogger("news_radar.notify")

# The page prints `09:30 06/09` beside a story and nothing else; a message that
# prints the same story with a source id and no time is a second report, not the
# same one. The format is duplicated from `render._when()` rather than imported:
# `render` and `notify` are the two halves of layer 5 and neither owns the
# other, and one strftime is cheaper than a dependency between them.
# `tests/test_notify.py` asserts the two spellings agree, so the duplication
# cannot drift quietly.
TIME_FMT = "%H:%M %d/%m"

# What an undated story renders as - the page's own honest dash. A source that
# gave no `pubDate` is not a story published at midnight.
NO_TIME = "--"

UTC = dt.timezone.utc

# The longest title that goes into a message. Long enough that no real headline
# is touched, short enough that title + link can never on their own overflow the
# smaller of the two channel budgets and cost the story its message.
TITLE_MAX = 240

# The minimum gap between two sends, whatever `advanced.request_interval_ms`
# says about feeds. One message per story means a busy cycle posts twenty of
# them back to back, and Telegram allows about 20 a minute to one group before
# answering 429 - at which point `send()` gives up on the channel for the whole
# cycle. Three and a half seconds sits under that with room to spare, and
# Discord's webhook budget (5 requests per 5 seconds) is comfortable there too.
# `__main__._notify()` builds its own Fetcher with this rather than reusing the
# crawl's, which is tuned for reading feeds.
NOTIFY_INTERVAL_MS = 3500


@dataclass
class SendResult:
    """What one channel did with one run.

    `keys` is the dedup keys of the messages the channel **accepted**, and it
    is the only thing `mark_reported()` is ever given. A message that failed
    leaves its story unreported, so the next run tries it again.
    """

    sent: int = 0
    failed: int = 0
    keys: tuple = field(default_factory=tuple)

    @property
    def stories(self):
        return len(self.keys)


def stamp(moment, tz):
    """`published_at` as the page spells it, or the same dash the page uses.

    The zone is an argument rather than the host's own: the page is rendered in
    `app.timezone`, and a message an hour out from the page it mirrors is worse
    than no timestamp at all.
    """
    if moment is None:
        return NO_TIME
    return moment.astimezone(tz).strftime(TIME_FMT)


def clip(text, limit=TITLE_MAX):
    """`text` shortened to `limit` characters, with an ellipsis when it was."""
    text = text or ""
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def pick(rows_by_label, labels, keys=None):
    """`{label: [row]}` -> `[(label, [row])]` in the keyword file's own order.

    Three jobs, all of which decide what a channel is even shown:

    - **Order.** `labels` is the group order the keyword file fixes, the same
      one the page renders in. A mapping's own order would shuffle the sections
      between runs for no reason a reader could follow.
    - **The diff.** `keys` is the seen-set answer - the stories this channel has
      not been told about. `None` means send everything (`report.mode: current`);
      an *empty* set means everything has already been sent, which is not the
      same thing and must send nothing at all.
    - **One story, one appearance.** A story matching two groups has a row in
      each, and a message that prints it twice - same headline, same link, same
      AI sentence - is the reader scrolling past their own report. It goes out
      under the **first** group in `labels` that claims it, and the operator
      controls which that is by ordering the groups in `frequency_words.txt`.

    That last job is the one place a message deliberately diverges from the
    page. The page is browsed by topic, so a story belonging to two topics
    belongs in both sections; a message is read top to bottom once, so the
    second copy is pure noise. Both channels get this for free - they are the
    two callers of this function.

    Marking follows: the accepted key goes into `reported` once, so the copy
    that was dropped here is not owed a message next cycle either.

    A group left empty by any of the three is dropped. The page prints the
    quiet keyword because someone is looking for it; a phone should not buzz to
    say nothing happened.
    """
    out = []
    seen = set()
    for label in labels:
        rows = rows_by_label.get(label) or []
        if keys is not None:
            rows = [row for row in rows if row["dedup_key"] in keys]

        kept = []
        for row in rows:
            if row["dedup_key"] in seen:
                continue
            seen.add(row["dedup_key"])
            kept.append(row)

        if kept:
            out.append((label, kept))
    return out


def messages(blocks, limit):
    """`[(header, [(line, key)])]` -> `[(text, keys)]`, one message per story.

    A group used to travel as one message with a bullet per story, split only
    when it outgrew the channel's budget. It is now **one message per story**,
    each carrying its own group header. A phone shows one story at a glance
    instead of a wall of ten, and a reply, a forward or a reaction is about
    that story rather than about the batch it happened to arrive in.

    The header is repeated on every message rather than sent once: a bare link
    with no group name says nothing about why the radar picked it up, and every
    message is now read on its own.

    A story longer than `limit` is **clipped, never split**. Half a headline
    with no link is worse than a shortened one, and `clip()` has already capped
    the title - what can still overrun is an AI sentence, and losing its tail
    costs nothing the link does not carry.

    An empty group contributes nothing. The page prints `0 item(s)` for a
    keyword that has gone quiet because a reader is looking for exactly that;
    a message pushed to a phone is not the place to say nothing happened.
    """
    out = []
    for header, items in blocks:
        for line, key in items:
            out.append((clip("{}\n{}".format(header, line), limit), (key,)))
    return out
