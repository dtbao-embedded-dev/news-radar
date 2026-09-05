"""Keeping the radar alive without being watched: the heartbeat.

Layer 5, beside `render.py` and `notify/`. Like them it imports **layer 1** for
the transport and nothing else - no config, no clock, no store. The two urls and
the verdict on the cycle all arrive as arguments, which is why
`tests/test_ops.py` exercises every path against a local `http.server` with
nothing installed and nothing configured.

The problem this file solves is that **a radar cannot report its own death.**
`run()` already survives a crashing cycle and logs it, but a container that was
killed, a host that lost power and a Docker daemon that never came back all look
identical from inside: silence. The answer is to make silence itself the signal
- something outside this process expects a request on a schedule and complains
when it stops arriving.

So one rule governs the whole file: **a ping is a claim that the cycle worked.**
Everything here exists to keep that claim from being made falsely - which is why
the site check happens *before* the ping and a failed check withholds it.

Contract: docs/memory-ai/interface/config-and-env.md (`ops.*`)
"""

from __future__ import annotations

import logging

from .fetch.http import HttpError

__all__ = ["heartbeat"]

log = logging.getLogger("news_radar.ops")


def heartbeat(fetcher, site_url, ping_url, healthy=True):
    """Check the published site, then ping the switch. Returns a problem list.

    `healthy` is the caller's verdict on everything that happened before this -
    the fetch, the store, the page, the senders. This function adds the one
    thing the cycle cannot see about itself: whether the report it just wrote is
    actually reachable from outside.

    Three deliberate asymmetries, each of them a failure this project has
    already had:

    - **The site check is a problem; a failed ping is not.** An unreachable page
      means the reader gets Cloudflare `1033` while every log line says success.
      A refused *ping* means the monitor is down - the radar is fine, and the
      thing that would have told us so is the thing that broke. Alerting on that
      trains you to ignore the alert.
    - **The site is checked even when the cycle already failed**, so the log
      carries both facts rather than only the first one found. Only the ping is
      withheld.
    - **Nothing here raises.** It runs at the end of a finished cycle; a bad url
      in the config must cost a line in the log, never the run that produced the
      page.

    Either url empty switches that half off, which is what ships.
    """
    problems = []

    if site_url:
        try:
            fetcher.get(site_url)
            log.info("heartbeat: %s answered", site_url)
        except HttpError as exc:
            problems.append(
                "the published site is unreachable: {} - {}".format(site_url, exc))

    if problems or not healthy:
        # Withheld on purpose. The monitor's own alarm is the second half of
        # this signal: saying nothing is how the outside world finds out.
        log.warning("heartbeat: cycle unhealthy, the ping is withheld")
        return problems

    if not ping_url:
        return problems

    try:
        fetcher.get(ping_url)
        log.info("heartbeat: pinged")
    except HttpError as exc:
        log.warning("heartbeat: the monitor refused the ping (%s) - the radar "
                    "is fine, the switch will trip anyway", exc)

    return problems
