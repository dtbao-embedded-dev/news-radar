#!/usr/bin/env python3
"""Checks for src/news_radar/fetch/http.py - plain asserts, no test framework.

    python tests/test_http.py

Standard library only, and it never leaves the machine: a local http.server
plays every source behaviour that matters - a 403 like Reddit's, a 500 worth
retrying, a body that arrives gzipped, and a handler slow enough to time out.
"""

from __future__ import annotations

import gzip
import http.server
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar.fetch import http as mod  # noqa: E402

FAILURES = []
HITS = {}
SEEN_HEADERS = {}


def check(name, condition, detail=""):
    if not condition:
        FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def eq(name, got, want):
    check(name, got == want, "got {!r}, want {!r}".format(got, want))


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # the test's own output is the only thing worth reading

    def do_GET(self):
        path = self.path
        HITS[path] = HITS.get(path, 0) + 1
        SEEN_HEADERS[path] = dict(self.headers)

        if path == "/403":
            self.send_error(403, "Blocked")
            return
        if path == "/500":
            self.send_error(500, "Server error")
            return
        if path == "/429":
            self.send_response(429)
            self.send_header("Retry-After", "0")
            self.end_headers()
            self.wfile.write(b"slow down")
            return
        if path == "/slow":
            time.sleep(1.0)
        if path == "/gzip":
            body = gzip.compress(b"<rss>gzipped</rss>")
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = b"<rss>ok</rss>"
        try:
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            # /slow is answered after the client has already timed out and hung
            # up. That is the point of the case; the abort is not a failure.
            pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
PORT = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()


def url(path, host="127.0.0.1"):
    return "http://{}:{}{}".format(host, PORT, path)


# --- the User-Agent, which is what unblocks Reddit -------------------------

UA = "news-radar/9.9.9 (+https://news.dtbao.org)"
f = mod.Fetcher(user_agent=UA, timeout_s=5, max_retries=0, interval_ms=0)

eq("a 200 body comes back as bytes", f.get(url("/ok")), b"<rss>ok</rss>")
eq("the configured User-Agent is sent",
   SEEN_HEADERS["/ok"].get("User-Agent"), UA)
check("gzip is offered, because Google News and Reddit both send it",
      "gzip" in (SEEN_HEADERS["/ok"].get("Accept-Encoding") or ""))
eq("a gzipped body is decompressed transparently",
   f.get(url("/gzip")), b"<rss>gzipped</rss>")

# An empty User-Agent is the config error behind Reddit's 403. Catching it at
# construction beats discovering it as a 403 on every Reddit source.
try:
    mod.Fetcher(user_agent="", timeout_s=5)
    FAILURES.append("Fetcher accepted an empty User-Agent")
except ValueError:
    pass


# --- retries: which statuses earn a second attempt, and which do not -------

HITS.clear()
f2 = mod.Fetcher(user_agent=UA, timeout_s=5, max_retries=2, backoff_s=0.01,
                 interval_ms=0)

try:
    f2.get(url("/500"))
    FAILURES.append("a persistent 500 did not raise")
except mod.HttpError as exc:
    eq("the error carries the status", exc.status, 500)
eq("a 500 is attempted 1 + max_retries times", HITS.get("/500"), 3)

try:
    f2.get(url("/403"))
    FAILURES.append("a 403 did not raise")
except mod.HttpError as exc:
    eq("the 403 error carries the status", exc.status, 403)
# Reddit's 403 is a decision about the request, not a hiccup. Retrying it costs
# two more requests and three times the delay for the same answer.
eq("a 403 is not retried", HITS.get("/403"), 1)

try:
    f2.get(url("/429"))
    FAILURES.append("a persistent 429 did not raise")
except mod.HttpError as exc:
    eq("the 429 error carries the status", exc.status, 429)
eq("a 429 is retried - it means later, not never", HITS.get("/429"), 3)

f3 = mod.Fetcher(user_agent=UA, timeout_s=0.2, max_retries=1, backoff_s=0.01,
                 interval_ms=0)
HITS.clear()
try:
    f3.get(url("/slow"))
    FAILURES.append("a request past the timeout did not raise")
except mod.HttpError:
    pass
eq("a timeout is retried", HITS.get("/slow"), 2)


# --- the per-host throttle ------------------------------------------------

f4 = mod.Fetcher(user_agent=UA, timeout_s=5, max_retries=0, interval_ms=300)

f4.get(url("/ok"))
start = time.monotonic()
f4.get(url("/ok"))
same_host = time.monotonic() - start
check("get() spaces two requests to one host by interval_ms",
      same_host >= 0.28, "{:.3f}s".format(same_host))

# The keying is measured on the map rather than through two real hostnames:
# on Windows `localhost` resolves to ::1 first, and the connection refused
# there costs seconds of fallback that would swamp a 300 ms measurement. What
# is under test is that the interval is per hostname - hn and hn_algolia are
# different hosts and must not queue behind each other, while the fixed Reddit
# feed and the Reddit search are the same host and must.
f5 = mod.Fetcher(user_agent=UA, timeout_s=5, max_retries=0, interval_ms=300)
f5._throttle("hn.algolia.com")
start = time.monotonic()
f5._throttle("hn.algolia.com")
check("a second call for the same host waits out the interval",
      time.monotonic() - start >= 0.28)
start = time.monotonic()
f5._throttle("news.google.com")
check("a different host does not wait for the first one's interval",
      time.monotonic() - start < 0.05)

start = time.monotonic()
eq("the first request to a host is not delayed at all",
   mod.Fetcher(user_agent=UA, timeout_s=5, interval_ms=5000).get(url("/ok")),
   b"<rss>ok</rss>")
check("...measurably so", time.monotonic() - start < 1.0)


# --- what a caller may not do ---------------------------------------------

try:
    f.get("ftp://example.com/feed.xml")
    FAILURES.append("a non-http scheme was fetched")
except mod.HttpError:
    pass


server.shutdown()

# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f_ in FAILURES:
        print("  - {}".format(f_))
    sys.exit(1)

print("OK")
