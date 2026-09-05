#!/usr/bin/env python3
"""Checks for src/news_radar/fetch/http.py - plain asserts, no test framework.

    python tests/test_http.py

Standard library only, and it never leaves the machine: a local http.server
plays every source behaviour that matters - a 403 like Reddit's, a 500 worth
retrying, a body that arrives gzipped, a handler slow enough to time out, and
the two shapes a throttled notification channel answers with.
"""

from __future__ import annotations

import gzip
import http.server
import json
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar.fetch import http as mod  # noqa: E402

FAILURES = []
HITS = {}
SEEN_HEADERS = {}
SEEN_BODIES = {}


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

    def do_POST(self):
        """The notification side: what Telegram and Discord answer with.

        The two 429 shapes are both real - Telegram puts the delay in
        `parameters.retry_after` and Discord at the top level, and neither of
        them is guaranteed to also send the header.
        """
        path = self.path
        HITS[path] = HITS.get(path, 0) + 1
        SEEN_HEADERS[path] = dict(self.headers)
        SEEN_BODIES[path] = self.rfile.read(
            int(self.headers.get("Content-Length") or 0))

        if path == "/post/429-header":
            self._reply(429, b'{"ok":false}', {"Retry-After": "0"})
            return
        if path == "/post/429-body":
            self._reply(429, b'{"ok":false,"parameters":{"retry_after":0}}')
            return
        if path == "/post/429-huge":
            self._reply(429, b'{"retry_after":9000}', {"Retry-After": "9000"})
            return
        if path == "/post/400":
            self._reply(400, b'{"ok":false,"description":"chat not found"}')
            return
        self._reply(200, b'{"ok":true}')

    def _reply(self, status, body, headers=()):
        self.send_response(status)
        for name, value in dict(headers).items():
            self.send_header(name, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


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


# --- POST, which is how a notification channel is talked to ---------------

HITS.clear()
f6 = mod.Fetcher(user_agent=UA, timeout_s=5, max_retries=2, backoff_s=0.01,
                 interval_ms=0)

eq("a 200 answer to a POST comes back as bytes",
   f6.post_json(url("/post/ok"), {"chat_id": 7, "text": "hi"}),
   b'{"ok":true}')
eq("the payload arrives as JSON",
   json.loads(SEEN_BODIES["/post/ok"]), {"chat_id": 7, "text": "hi"})
eq("a POST declares its content type",
   SEEN_HEADERS["/post/ok"].get("Content-Type"), "application/json")
eq("a POST carries the same User-Agent as a GET",
   SEEN_HEADERS["/post/ok"].get("User-Agent"), UA)

# An OpenAI-compatible endpoint authenticates with a header, and it is the only
# reason `post_json()` takes any. What the caller adds must reach the server
# without displacing anything the transport decided for itself - a bearer token
# that cost the User-Agent would answer 403 on the feeds' behalf.
eq("a 200 answer to an authenticated POST comes back as bytes",
   f6.post_json(url("/post/auth"), {"model": "m"},
                headers={"Authorization": "Bearer t"}),
   b'{"ok":true}')
eq("a caller-supplied header reaches the server",
   SEEN_HEADERS["/post/auth"].get("Authorization"), "Bearer t")
eq("a caller-supplied header leaves the User-Agent alone",
   SEEN_HEADERS["/post/auth"].get("User-Agent"), UA)
eq("a caller-supplied header leaves the content type alone",
   SEEN_HEADERS["/post/auth"].get("Content-Type"), "application/json")

# 429 is the one status where the server says how long to wait, and both
# channels do. Sleeping our own exponential guess instead is how a bot gets
# itself banned rather than throttled.
try:
    f6.post_json(url("/post/429-header"), {})
    FAILURES.append("a persistent 429 on POST did not raise")
except mod.HttpError as exc:
    eq("the POST 429 carries the status", exc.status, 429)
    eq("Retry-After is read off the header", exc.retry_after, 0.0)
eq("a 429 POST is retried like a 429 GET", HITS.get("/post/429-header"), 3)

try:
    f6.post_json(url("/post/429-body"), {})
    FAILURES.append("a 429 with the delay only in the body did not raise")
except mod.HttpError as exc:
    eq("Telegram's parameters.retry_after is read too", exc.retry_after, 0.0)

# A hostile or merely optimistic server asking for fifteen minutes would stall
# the cycle past its own interval; the run is better off failing this channel
# and moving on.
f7 = mod.Fetcher(user_agent=UA, timeout_s=5, max_retries=0, interval_ms=0)
try:
    f7.post_json(url("/post/429-huge"), {})
    FAILURES.append("a 429 asking for 9000s did not raise")
except mod.HttpError as exc:
    eq("Retry-After is capped", exc.retry_after, mod.RETRY_AFTER_MAX)

HITS.clear()
try:
    f6.post_json(url("/post/400"), {})
    FAILURES.append("a 400 on POST did not raise")
except mod.HttpError as exc:
    eq("the 400 carries the status", exc.status, 400)
    check("the 400 keeps the body, which is where the reason is",
          b"chat not found" in exc.body, repr(exc.body))
# A bad token, a bad chat id or a malformed body answers the same way however
# many times it is asked.
eq("a 400 is not retried", HITS.get("/post/400"), 1)


# --- what a caller may not do ---------------------------------------------

try:
    f.get("ftp://example.com/feed.xml")
    FAILURES.append("a non-http scheme was fetched")
except mod.HttpError:
    pass

try:
    f.post_json("ftp://example.com/hook", {})
    FAILURES.append("a non-http scheme was posted to")
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
