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


def _fetcher(cfg):
    """One Fetcher per cycle: the per-host throttle state lives on it."""
    return Fetcher(
        user_agent=cfg.user_agent(),
        timeout_s=cfg.get("advanced.request_timeout_s", 15),
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


def crawl(cfg):
    """One pass: fetch, filter, rank, store, render, notify.

    P1 and P2 have landed: this returns the ranked shortlist, grouped by
    keyword group. Storage, the page and the senders are still ahead, so the
    cycle ends by printing the shortlist rather than claiming it published one.
    """
    started = time.monotonic()
    fetched_at = dt.datetime.now(dt.timezone.utc)
    fetcher = _fetcher(cfg)

    try:
        groups, global_filter = parse_keywords(cfg.get("keywords.file"))
    except KeywordError as exc:
        # The fixed feeds do not need the keyword file; only the search feeds
        # do. Losing half the run is better than losing all of it, and the
        # reason is on one line rather than in a traceback.
        log.error("keyword file unusable, search feeds skipped this cycle: %s", exc)
        groups, global_filter = [], []

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
    log.warning("storage, the page and the senders are not implemented yet "
                "(P3, P4) - nothing is published or notified this cycle")
    return ranked


def run(cfg, once=False):
    """The schedule loop. Returns the process exit code."""
    interval_s = cfg.get("schedule.interval_minutes", 30) * 60
    run_on_start = cfg.get("schedule.run_on_start", True)

    if once:
        crawl(cfg)
        return 0

    if not run_on_start:
        log.info("schedule.run_on_start is false, waiting %d minute(s) first",
                 interval_s // 60)
        if _stop.wait(interval_s):
            return 0

    while not _stop.is_set():
        try:
            crawl(cfg)
        except Exception:
            # One bad cycle must not end the service. The traceback goes to the
            # log and the next cycle runs; a crash loop would lose the schedule
            # entirely and docker would restart us into the same failure.
            log.exception("crawl failed, continuing to the next cycle")

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
