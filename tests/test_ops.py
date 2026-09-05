#!/usr/bin/env python3
"""Checks for src/news_radar/ops.py - plain asserts, no test framework.

    python tests/test_ops.py

Standard library only, and it never leaves the machine: a local http.server
plays both the published site and the dead-man's switch, including the answers
that must withhold a ping rather than send one.

The rule this file exists to pin: **a ping is a claim that the cycle worked.**
Every check below is one way that claim could be made falsely.
"""

from __future__ import annotations

import http.server
import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar import ops  # noqa: E402
from news_radar.fetch.http import Fetcher  # noqa: E402

FAILURES = []
HITS = {}


def check(name, condition, detail=""):
    if not condition:
        FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def eq(name, got, want):
    check(name, got == want, "got {!r}, want {!r}".format(got, want))


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        HITS[self.path] = HITS.get(self.path, 0) + 1

        if "down" in self.path:
            # 502 is what a Cloudflare tunnel with no connector looks like from
            # outside, which is the failure this whole check exists for.
            self._reply(502, b"Bad Gateway")
            return
        if "bad" in self.path:
            # A revoked or mistyped ping url. Not retried, and not our problem
            # to alert on: the monitor notices its own missing ping.
            self._reply(404, b"Not Found")
            return
        self._reply(200, b"<html><title>news-radar</title></html>")

    def _reply(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
PORT = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()


def url(path):
    return "http://127.0.0.1:{}{}".format(PORT, path)


# max_retries=0: a 502 is retryable, and this file counts requests.
fetcher = Fetcher(user_agent="news-radar/9.9.9 (+https://news.dtbao.org)",
                  timeout_s=5, max_retries=0, backoff_s=0.01, interval_ms=0)


# --- the happy path -------------------------------------------------------

problems = ops.heartbeat(fetcher, url("/site"), url("/ping"), healthy=True)
eq("a clean cycle against a live site reports no problem", problems, [])
eq("...and checks the site exactly once", HITS.get("/site"), 1)
eq("...and pings exactly once", HITS.get("/ping"), 1)


# --- the site is down: withhold the ping, and say why ---------------------

problems = ops.heartbeat(fetcher, url("/site-down"), url("/ping"), healthy=True)
eq("a site answering 502 is one problem", len(problems), 1)
check("the problem names the url that failed", url("/site-down") in problems[0],
      problems[0])
eq("...and the ping is withheld, so the monitor notices too",
   HITS.get("/ping"), 1)


# --- the cycle itself failed: withhold the ping too -----------------------

problems = ops.heartbeat(fetcher, url("/site"), url("/ping"), healthy=False)
eq("an unhealthy cycle adds no problem of its own here", problems, [])
eq("...and does not ping, whatever the site says", HITS.get("/ping"), 1)
eq("...but the site is still checked, so the log carries both facts",
   HITS.get("/site"), 2)


# --- both keys empty: the shipped default is inert ------------------------

problems = ops.heartbeat(fetcher, "", "", healthy=True)
eq("a config with no ops urls reports nothing", problems, [])
eq("...and makes no request at all", sum(HITS.values()), 4)


# --- one key at a time ----------------------------------------------------

problems = ops.heartbeat(fetcher, "", url("/ping-only"), healthy=True)
eq("no site_url means no site check, and the ping still fires", problems, [])
eq("...exactly once", HITS.get("/ping-only"), 1)

problems = ops.heartbeat(fetcher, url("/site"), "", healthy=True)
eq("no heartbeat_url still checks the site", problems, [])
eq("...and the site check ran", HITS.get("/site"), 3)


# --- a refused ping is a warning, never an alert --------------------------

# A monitor outage must not buzz the phone: the radar is fine, and the thing
# that would have told us so is the thing that broke.
problems = ops.heartbeat(fetcher, url("/site"), url("/ping-bad"), healthy=True)
eq("a 404 from the monitor is not a problem with the radar", problems, [])
eq("...and is not retried into a storm", HITS.get("/ping-bad"), 1)


# --- a garbage url cannot cost the cycle ----------------------------------

# config.validate() refuses these at startup, but heartbeat() is called with
# whatever the caller has and must not raise out of a finished cycle.
problems = ops.heartbeat(fetcher, "not-a-url", url("/ping"), healthy=True)
eq("an unusable site_url is one problem, not an exception", len(problems), 1)
eq("...and still withholds the ping", HITS.get("/ping"), 1)


server.shutdown()

# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
