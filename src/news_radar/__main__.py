"""Entrypoint: `python -m news_radar`.

Owns the schedule loop and nothing else. Every stage it will call lives in its
own module; this file wires them together and is the only place that knows about
all of them.

    python -m news_radar            # loop forever on schedule.interval_minutes
    python -m news_radar --once     # one cycle, then exit
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import logging
import os
import signal
import sys
import threading
import time

from . import __version__
from .config import ConfigError, load
from .fetch.feeds import read_fixed_feeds
from .fetch.http import Fetcher
from .fetch.search import read_search_feeds
from .filter import select
from .keywords import KeywordError, parse as parse_keywords
from .rank import collapse, rank_groups
from . import notify, ops, render, store, summarize
from .notify import discord, telegram

log = logging.getLogger("news_radar")

# Set by the signal handlers; the loop waits on it instead of sleeping, so a
# `docker stop` is honoured immediately rather than up to interval_minutes
# later - and docker only waits 10 seconds before SIGKILL.
_stop = threading.Event()


def _install_signal_handlers():
    def handler(signum, _frame):
        log.info("signal %s received, finishing and shutting down", signum)
        _stop.set()

    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is not None:
            signal.signal(sig, handler)


def _fetcher(cfg, timeout_s=None):
    """One Fetcher per cycle: the per-host throttle state lives on it.

    `timeout_s` overrides the feed timeout for the one caller that needs it: a
    chat completion is slower than an RSS file by an order of magnitude, and
    fifteen seconds would time out every summary while looking like an outage.
    """
    return Fetcher(
        user_agent=cfg.user_agent(),
        timeout_s=timeout_s or cfg.get("advanced.request_timeout_s", 15),
        max_retries=cfg.get("advanced.max_retries", 2),
        interval_ms=cfg.get("advanced.request_interval_ms", 2000),
    )


def _report_counts(items, sources, errors):
    """One line per configured source, including the ones that brought nothing.

    A source that quietly stops returning items looks exactly like a quiet week
    in a total. Naming every source, zeros included, is what makes the
    difference visible without reading the whole debug log.
    """
    counted = collections.Counter(i.source_id for i in items)
    failed = {source_id for source_id, _ in errors}
    for source_id in sources:
        log.info("  %-18s %4d item(s)%s", source_id, counted.get(source_id, 0),
                 "  [failed]" if source_id in failed else "")


def _source_weights(cfg):
    """{source_id: rank_weight} over every configured source, enabled or not.

    Layer 3 may not import `config`, so the map is built here and handed down.
    Disabled entries are included on purpose: an item is scored by where it came
    from, and a source switched off after this cycle started still carries the
    weight the operator gave it.
    """
    weights = {}
    for entry in (cfg.get("feeds") or []) + (cfg.get("search_templates") or []):
        source_id = entry.get("id")
        if isinstance(source_id, str):
            weights[source_id] = entry.get("rank_weight", 1.0)
    return weights


def _report_groups(ranked):
    """The shortlist itself: one line per group, then the stories it kept.

    Empty groups are printed too. A keyword that has gone quiet looks exactly
    like a keyword nobody wrote about, and the difference is the whole reason
    to read the log.
    """
    for label, stories in ranked.items():
        log.info("  %s - %d item(s)", label, len(stories))
        for story in stories:
            log.info("    %.2f  %s  [%s]", story.score, story.item.title,
                     ", ".join(story.source_ids))


def _summarize(cfg, day, labels):
    """Today's AI summary, or None. Never a reason the cycle failed.

    Off is the shipped case, and the whole point of P6-4's reversal: `ai.enabled`
    defaults to false, so a config that says nothing about `ai` never reaches
    the network and never sees a bill.

    Guarded even though `summarize.summarize()` already swallows every failure
    of its own: the Fetcher constructor refuses an empty User-Agent, and the one
    thing an *optional* feature may never do is take the page down with it. That
    is also why the caller adds nothing to `problems` - an endpoint having a bad
    afternoon is not a news-radar outage, and it must not withhold the ping.
    """
    if not cfg.get("ai.enabled"):
        return None
    try:
        return summarize.summarize(
            _fetcher(cfg, cfg.get("ai.timeout_s", 60)),
            cfg.get("ai.api_url"), os.environ.get("OPENAI_API_KEY"),
            cfg.get("ai.model"), day, labels,
            cfg.get("ai.max_per_topic", 5))
    except Exception:
        log.exception("the summary failed; the page is written without one")
        return None


def _publish(cfg, ranked, groups, fetched_at, fetched, matched, errors):
    """Persist the run and rewrite the page. Returns `(run_id, summary)`.

    The id is what the senders read the run back by, so a cycle whose storage
    failed notifies nothing rather than notifying a run that was never written.
    The summary is produced here rather than in `crawl()` because it is built
    from the same `day` rows the page renders - one read of the store, and the
    paragraph at the top of the page describes exactly what is under it.

    Guarded as a whole, for the same reason the keyword file is: a full disk, a
    locked database or a read-only volume must not throw away the 597 items that
    took forty seconds to collect. The cycle logs it and still returns the
    shortlist.
    """
    data_dir = cfg.get("storage.data_dir", "output")
    conn = None
    summary = None
    try:
        conn = store.open_db(data_dir)
        run_id = store.start_run(conn, fetched_at)
        rows = store.save(conn, run_id, ranked, fetched_at)

        tz = render.local_tz(cfg.get("app.timezone") or "UTC")
        start, end = render.day_bounds(fetched_at, tz)
        # Read back from the store rather than rendering `ranked` directly: the
        # page shows the whole local day, so a restart at noon still publishes
        # what the morning found.
        day = store.day_matches(conn, start, end)

        if groups:
            summary = _summarize(cfg, day, [g.label for g in groups])
            render.write(
                data_dir, [g.label for g in groups], day,
                {"run_id": run_id, "fetched": fetched, "matched": matched,
                 "sources": len(cfg.enabled_feeds())
                            + len(cfg.enabled_search_templates()),
                 "errors": len(errors), "generated_at": fetched_at},
                tz, threshold=cfg.get("report.rank_threshold", 5),
                summary=summary)
        else:
            # No keyword file means no group order to render in, and a page with
            # no sections at all is worse than yesterday's page: it reads as "no
            # news" rather than "the radar is broken".
            log.warning("no keyword group this cycle, the page is left as it "
                        "was rather than rewritten empty")

        # Before the prune, and inside the same guard, on purpose: if the copy
        # cannot be written the deletion below never runs either. No backup, no
        # deletion is the one ordering worth being strict about.
        store.backup(conn, cfg.get("ops.backup_dir", "backups"), fetched_at,
                     cfg.get("ops.backup_keep", 7))
        store.prune(conn, data_dir, cfg.get("storage.retention_days", 0),
                    fetched_at)
        store.finish_run(conn, run_id, dt.datetime.now(dt.timezone.utc),
                         items_fetched=fetched, items_matched=matched,
                         errors=errors)

        # Counted over the *rendered* labels, not over `day`. The two are the
        # same until someone edits the keyword file mid-day: the store still
        # holds this morning's rows for a group that no longer exists, and
        # `render.write()` walks `labels` rather than the mapping, so those rows
        # are on disk and not on the page. A line beginning "the page shows"
        # has to mean the page.
        labels = [g.label for g in groups]
        log.info("stored %d match row(s) as run %s; the page shows %d "
                 "story(ies) across %d group(s) today", rows, run_id,
                 sum(len(day.get(label) or []) for label in labels),
                 len(labels))
        return run_id, summary
    except Exception:
        log.exception("storing or rendering failed, the fetched items are kept")
        return None, None
    finally:
        if conn is not None:
            conn.close()


def _send_telegram(fetcher, groups, env):
    return telegram.send(fetcher, groups, env.get("TELEGRAM_BOT_TOKEN"),
                         env.get("TELEGRAM_CHAT_ID"))


def _send_discord(fetcher, groups, env):
    return discord.send(fetcher, groups, env.get("DISCORD_WEBHOOK_URL"))


def _alert_telegram(fetcher, text, env):
    return telegram.alert(fetcher, text, env.get("TELEGRAM_BOT_TOKEN"),
                          env.get("TELEGRAM_CHAT_ID"))


def _alert_discord(fetcher, text, env):
    return discord.alert(fetcher, text, env.get("DISCORD_WEBHOOK_URL"))


# Channel name (as `notification.channels` spells it) -> how to send on it. The
# secrets are read here and handed down, so a channel module needs no
# environment to be exercised.
SENDERS = {telegram.NAME: _send_telegram, discord.NAME: _send_discord}

# The same channels, carrying an operational message instead of a story. A
# separate table rather than a flag on the one above: the two payloads share a
# transport and nothing else, and an alert must go out on a channel whose
# story-sending has already been refused this cycle.
ALERTERS = {telegram.NAME: _alert_telegram, discord.NAME: _alert_discord}


def _alert(cfg, text):
    """Push one operational message to every enabled channel.

    Guarded per channel like `_notify()` is, and for a harder reason: this runs
    *because* something already went wrong, so it is the least surprising place
    in the program for a second thing to go wrong. Nothing it does may end the
    schedule loop.
    """
    channels = [c for c in cfg.enabled_channels() if c in ALERTERS]
    if not channels:
        log.warning("no channel is enabled, so nobody is being told: %s", text)
        return

    fetcher = _fetcher(cfg)
    taken = []
    for name in channels:
        try:
            if ALERTERS[name](fetcher, text, os.environ):
                taken.append(name)
        except Exception:
            log.exception("could not alert on %s; the other channels and the "
                          "loop are unaffected", name)

    # Logged at WARNING, and logged even when every channel took it. Found by
    # the P6 live run: an alert that succeeded left no line at all, so the only
    # trace of one in `docker logs` was an unexplained two-second gap. A feature
    # whose whole purpose is visibility may not be the quietest thing in the
    # file.
    log.warning("alerted %d of %d channel(s) [%s]: %s",
                len(taken), len(channels), ", ".join(taken) or "none",
                text.replace("\n", " | "))


def _rows_to_send(cfg, conn, run_id, fetched_at):
    """The store rows `report.mode` selects, before the seen-set diff.

    `daily` reads the whole local day, the other two read this run. Both come
    out of the store rather than out of `ranked`, so the story that goes out is
    the same row, with the same score, as the one on the page.
    """
    if cfg.get("report.mode") == "daily":
        tz = render.local_tz(cfg.get("app.timezone") or "UTC")
        return store.day_matches(conn, *render.day_bounds(fetched_at, tz))
    return store.run_matches(conn, run_id)


def _send_channel(conn, cfg, fetcher, name, rows, labels, now):
    """One channel: diff, send, and mark only what was accepted."""
    keys = None
    if cfg.get("report.mode") != "current":
        # `current` re-sends the run's whole shortlist by design. The other two
        # modes ask the seen-set, which is per channel: a story pushed to
        # Telegram is still unsent on Discord.
        every = [row["dedup_key"] for label in labels
                 for row in rows.get(label) or []]
        keys = set(store.unreported(conn, every, name))

    groups = notify.pick(rows, labels, keys)
    if not groups:
        log.info("  %-8s nothing new to send", name)
        return

    result = SENDERS[name](fetcher, groups, os.environ)
    if result.keys:
        # Only now, and only what was accepted. A crash between the send and
        # this line re-sends next cycle - a duplicate is the acceptable
        # failure, a silently dropped story is not.
        store.mark_reported(conn, result.keys, name, now)

    log.info("  %-8s %d message(s), %d story(ies)%s", name, result.sent,
             result.stories, ", {} refused".format(result.failed)
             if result.failed else "")


def _notify(cfg, fetcher, run_id, labels, fetched_at):
    """Push the run's new stories to every enabled channel.

    Two levels of guard, and both are in the contract. The outer one keeps a
    locked store or an unreadable run from costing the page, which is already
    written by the time this runs. The inner one is per channel: a dead webhook
    must leave the *other* channel still attempted, so it cannot be allowed to
    unwind the loop.
    """
    channels = [c for c in cfg.enabled_channels() if c in SENDERS]
    if not channels:
        log.info("no notification channel is enabled, nothing is sent")
        return

    log.info("notifying %d channel(s) in %s mode", len(channels),
             cfg.get("report.mode"))
    conn = None
    try:
        conn = store.open_db(cfg.get("storage.data_dir", "output"))
        rows = _rows_to_send(cfg, conn, run_id, fetched_at)
        for name in channels:
            try:
                _send_channel(conn, cfg, fetcher, name, rows, labels, fetched_at)
            except Exception:
                log.exception("channel %s failed; the page and the other "
                              "channels are unaffected", name)
    except Exception:
        log.exception("notification failed, the page is unaffected")
    finally:
        if conn is not None:
            conn.close()


def _send_summary(cfg, summary, fetched_at):
    """Push the day's summary to every enabled channel, once per local day.

    The page gets a fresh summary every cycle; a phone gets one a day. That
    asymmetry is the whole design: the page is somewhere you go and the message
    is something that interrupts you, and forty-eight interruptions a day
    saying roughly the same thing is how a channel gets muted - taking the
    outage alerts with it.

    "Once" survives a restart because it is not remembered in memory. The
    `reported` table already answers *"has this channel been told about X"* per
    channel and idempotently, so the summary rides in it under
    `summarize.daily_key()` - no schema, no second mechanism, and a container
    that came back at noon still knows this morning's went out.

    Sent through the channels' `alert()` rather than `send()`: a summary is
    sentences, not a list of links, which is exactly the payload `alert()` was
    shaped for - and on Telegram that means no `parse_mode`, so an em dash or a
    stray `<` from a model cannot cost the message.

    Guarded throughout. Nothing here may end the cycle: the page is already
    written by the time it runs.
    """
    if not summary:
        return

    tz = render.local_tz(cfg.get("app.timezone") or "UTC")
    local = fetched_at.astimezone(tz)
    hour = cfg.get("ai.notify_at_hour", 8)
    if local.hour < hour:
        log.info("summary: holding until %02d:00 local", hour)
        return

    channels = [c for c in cfg.enabled_channels() if c in ALERTERS]
    if not channels:
        return

    key = summarize.daily_key(local.date())
    conn = None
    try:
        conn = store.open_db(cfg.get("storage.data_dir", "output"))
        todo = [c for c in channels if store.unreported(conn, [key], c)]
        if not todo:
            log.info("summary: already sent today")
            return

        fetcher = _fetcher(cfg)
        taken = []
        for name in todo:
            try:
                if ALERTERS[name](fetcher, summary, os.environ):
                    # Marked per channel and only on acceptance, the same rule
                    # the stories follow: a refused message is retried next
                    # cycle rather than counted as delivered.
                    store.mark_reported(conn, [key], name, fetched_at)
                    taken.append(name)
            except Exception:
                log.exception("could not send the summary on %s; the other "
                              "channels and the cycle are unaffected", name)

        log.info("summary: sent to %d of %d channel(s) [%s]",
                 len(taken), len(todo), ", ".join(taken) or "none")
    except Exception:
        log.exception("sending the summary failed; the page and the run are "
                      "unaffected")
    finally:
        if conn is not None:
            conn.close()


def _dead_sources(cfg, errors):
    """A problem when *every* enabled source failed, and nothing otherwise.

    One dead source is already handled - `read_source()` isolates it and the
    per-source count prints `[failed]`. All of them at once is a different
    animal: a DNS outage, a dropped network, a proxy in front of the container.
    It looks exactly like a quiet news day in every line above it.
    """
    enabled = {entry.get("id") for entry in
               cfg.enabled_feeds() + cfg.enabled_search_templates()}
    failed = {source_id for source_id, _ in errors}
    if enabled and enabled <= failed:
        return ["every one of the {} enabled source(s) failed this "
                "cycle".format(len(enabled))]
    return []


def crawl(cfg):
    """One pass: fetch, filter, rank, store, render, notify, heartbeat.

    Returns `(ranked, problems)` - the shortlist, and the reasons this cycle
    should not be called a success. An empty problem list is what licenses the
    heartbeat ping, and two non-empty ones in a row are what `run()` turns into
    an alert.

    Nothing after the fetch can cost the shortlist: storage and rendering are
    guarded together, the senders separately, and a channel separately again.
    The problems are collected rather than raised for the same reason - a cycle
    that half-worked should publish the half that worked *and* say so.
    """
    started = time.monotonic()
    fetched_at = dt.datetime.now(dt.timezone.utc)
    fetcher = _fetcher(cfg)
    problems = []

    try:
        groups, global_filter = parse_keywords(cfg.get("keywords.file"))
    except KeywordError as exc:
        # The fixed feeds do not need the keyword file; only the search feeds
        # do. Losing half the run is better than losing all of it, and the
        # reason is on one line rather than in a traceback.
        log.error("keyword file unusable, search feeds skipped this cycle: %s", exc)
        groups, global_filter = [], []
        problems.append("the keyword file is unusable, so every search feed "
                        "was skipped: {}".format(exc))

    feed_items, feed_errors = read_fixed_feeds(fetcher, cfg, fetched_at=fetched_at)
    search_items, search_errors = read_search_feeds(
        fetcher, cfg, groups, fetched_at=fetched_at)

    items = feed_items + search_items
    errors = feed_errors + search_errors

    log.info("fixed feeds: %d item(s) from %d source(s)",
             len(feed_items), len(cfg.enabled_feeds()))
    _report_counts(feed_items, [f.get("id") for f in cfg.enabled_feeds()],
                   feed_errors)
    log.info("search feeds: %d item(s) from %d group(s) x %d template(s)",
             len(search_items), len(groups),
             len(cfg.enabled_search_templates()))
    _report_counts(search_items,
                   [t.get("id") for t in cfg.enabled_search_templates()],
                   search_errors)

    for source_id, reason in errors:
        log.warning("source failed: %s - %s", source_id, reason)

    log.info("fetched %d raw item(s) in %.1fs, %d source(s) failed",
             len(items), time.monotonic() - started, len(errors))

    matched = select(items, groups, global_filter)
    stories = collapse(matched)
    ranked = rank_groups(stories, groups, cfg.get("rank") or {},
                         _source_weights(cfg), fetched_at,
                         default_cap=cfg.get("report.max_per_group", 0))

    log.info("matched %d item(s) -> %d story(ies) after dedup -> %d kept "
             "across %d group(s)", len(matched), len(stories),
             sum(len(s) for s in ranked.values()), len(ranked))
    _report_groups(ranked)
    problems += _dead_sources(cfg, errors)

    run_id, summary = _publish(cfg, ranked, groups, fetched_at, len(items),
                               len(matched), errors)
    if run_id:
        # The summary goes first, and the order is the whole point: a cycle can
        # push dozens of story messages, and a summary sent after them is a
        # summary nobody scrolls back up to find. Observed on 2026-09-05, when
        # a keyword change made 43 stories newly unsent and buried the day's
        # summary under eighteen messages of links.
        #
        # Outside the problem list either way: the summary is optional, so a
        # failed one is a page without a paragraph and never a cycle that
        # withholds its heartbeat ping. Guarded separately too, so a refused
        # summary cannot cost the stories their turn.
        _send_summary(cfg, summary, fetched_at)
        _notify(cfg, fetcher, run_id, [g.label for g in groups], fetched_at)
    else:
        # `_publish` already logged the traceback. Without this line the cycle
        # would go on to ping the heartbeat and claim it succeeded, which is
        # the exact silent failure P6-1 exists to close.
        problems.append("storing or rendering failed - see the traceback above")

    # Last, and with the verdict on everything above it: the ping is a claim
    # that this cycle worked, so it is only ever made once that is known.
    problems += ops.heartbeat(fetcher, cfg.get("ops.site_url"),
                              cfg.get("ops.heartbeat_url"),
                              healthy=not problems)
    return ranked, problems


def run(cfg, once=False):
    """The schedule loop. Returns the process exit code."""
    interval_s = cfg.get("schedule.interval_minutes", 30) * 60
    run_on_start = cfg.get("schedule.run_on_start", True)

    if once:
        _, problems = crawl(cfg)
        for problem in problems:
            log.error("problem: %s", problem)
        return 0

    if not run_on_start:
        log.info("schedule.run_on_start is false, waiting %d minute(s) first",
                 interval_s // 60)
        if _stop.wait(interval_s):
            return 0

    # One tracker for the life of the process: what makes an outage two
    # messages instead of one every interval until somebody notices.
    health = ops.Health()

    while not _stop.is_set():
        try:
            _, problems = crawl(cfg)
        except Exception as exc:  # noqa: BLE001
            # One bad cycle must not end the service. The traceback goes to the
            # log and the next cycle runs; a crash loop would lose the schedule
            # entirely and docker would restart us into the same failure.
            log.exception("crawl failed, continuing to the next cycle")
            problems = ["the cycle raised {}: {}".format(
                type(exc).__name__, exc)]

        for problem in problems:
            log.error("problem: %s", problem)

        message = health.update(problems)
        if message:
            _alert(cfg, message)

        log.info("next crawl in %d minute(s)", interval_s // 60)
        if _stop.wait(interval_s):
            break

    log.info("stopped")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="news_radar",
        description="Hunt news on a schedule, filter it, publish and notify.",
    )
    parser.add_argument("--once", action="store_true",
                        help="run a single cycle and exit, ignoring the schedule")
    parser.add_argument("--config", default=None,
                        help="config file to use (default: $NEWS_RADAR_CONFIG)")
    parser.add_argument("--debug", action="store_true",
                        help="verbose per-source logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        stream=sys.stdout,
    )

    try:
        cfg = load(args.config)
    except ConfigError as exc:
        # Not a traceback: the operator needs the list of problems, not our
        # call stack. Exit 1 stops the container instead of looping on a
        # config that cannot work.
        log.error("configuration is not usable:\n%s", exc)
        return 1

    if args.debug or cfg.get("advanced.debug", False):
        logging.getLogger().setLevel(logging.DEBUG)

    log.info("news-radar %s starting (config: %s)", __version__, cfg.path)
    _install_signal_handlers()
    return run(cfg, once=args.once)


if __name__ == "__main__":
    sys.exit(main())
