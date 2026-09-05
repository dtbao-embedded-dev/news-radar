"""Entrypoint: `python -m news_radar`.

Owns the schedule loop and nothing else. Every stage it will call lives in its
own module; this file wires them together and is the only place that knows about
all of them.

    python -m news_radar            # loop forever on schedule.interval_minutes
    python -m news_radar --once     # one cycle, then exit
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

from . import __version__
from .config import ConfigError, load

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


def crawl(cfg):
    """One pass: fetch, filter, rank, store, render, notify.

    Not implemented. P1 lands the fetch layer here, P2 the selection, P3 the
    store and the page, P4 the senders. It logs what it *would* do and returns
    0 items rather than pretending: a loop that reports success while doing
    nothing is worse than one that says it is empty.
    """
    feeds = cfg.enabled_feeds()
    searches = cfg.enabled_search_templates()
    channels = cfg.enabled_channels()

    log.info(
        "would fetch %d fixed feed(s) and %d search template(s), "
        "reporting to %s",
        len(feeds), len(searches), ", ".join(channels) or "no channel",
    )
    log.warning("fetch is not implemented yet (P1) - 0 items this cycle")
    return 0


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
