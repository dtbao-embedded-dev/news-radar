#!/usr/bin/env python3
"""Checks for src/news_radar/summarize.py - plain asserts, no test framework.

    python tests/test_summarize.py

Standard library only, and it never leaves the machine: a local http.server
plays the OpenAI-compatible endpoint, including every way it can answer badly.

Two rules this file exists to pin:

- **The prompt is per topic, and a quiet topic is not in it.** The model must
  never be shown a group it would have to write "nothing today" about.
- **A summary is optional, so nothing here may raise.** Every failure the wire
  and a strange body can produce comes back as `None` and one log line.
"""

from __future__ import annotations

import http.server
import json
import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar import summarize  # noqa: E402
from news_radar.fetch.http import Fetcher  # noqa: E402

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
        pass

    def do_POST(self):
        path = self.path
        HITS[path] = HITS.get(path, 0) + 1
        SEEN_HEADERS[path] = dict(self.headers)
        SEEN_BODIES[path] = self.rfile.read(
            int(self.headers.get("Content-Length") or 0))

        if path == "/500":
            self._reply(500, b'{"error":"upstream is having a day"}')
            return
        if path == "/not-json":
            # A proxy or a captive portal answering 200 with an HTML error page
            # is the realistic shape of this, not a corrupted stream.
            self._reply(200, b"<html>gateway timeout</html>")
            return
        if path == "/empty-json":
            self._reply(200, b"{}")
            return
        if path == "/no-content":
            self._reply(200, b'{"choices":[{"message":{}}]}')
            return
        self._reply(200, json.dumps({
            "choices": [{"message": {
                "role": "assistant",
                "content": "  AI — Có hai bài đáng đọc.\nRust — Bản 1.9 ra.  ",
            }}],
        }).encode("utf-8"))

    def _reply(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
PORT = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()


def url(path):
    return "http://127.0.0.1:{}{}".format(PORT, path)


# max_retries=0: a 500 is retryable, and this file counts requests.
fetcher = Fetcher(user_agent="news-radar/9.9.9 (+https://news.dtbao.org)",
                  timeout_s=5, max_retries=0, backoff_s=0.01, interval_ms=0)


def row(title, score):
    return {"title": title, "score": score, "url": "https://e.invalid/x",
            "dedup_key": title, "sources": ("hn",)}


LABELS = ["AI", "Rust", "Quiet"]
ROWS = {
    # Already score DESC, which is the order store._matches() hands over.
    "AI": [row("A first", 9.0), row("A second", 8.0), row("A third", 7.0)],
    "Rust": [row("R first", 6.0)],
    "Quiet": [],
}


# --- build_prompt: pure, ordered, capped, and quiet groups left out -------

prompt = summarize.build_prompt(ROWS, LABELS, max_per_topic=2)

check("the prompt names the topics that have stories", "AI" in prompt
      and "Rust" in prompt, prompt)
check("a group with no story is not in the prompt at all",
      "Quiet" not in prompt, prompt)
check("the top stories of a topic are in", "A first" in prompt
      and "A second" in prompt, prompt)
check("max_per_topic is a cap, not a suggestion",
      "A third" not in prompt, prompt)
check("the labels order is the keyword file's order",
      prompt.index("AI") < prompt.index("Rust"), prompt)
check("the instruction asks for Vietnamese", "Vietnamese" in prompt, prompt)
check("the instruction bounds the sentences per topic",
      str(summarize.SENTENCES_MAX) in prompt, prompt)

eq("build_prompt does not mutate the rows it was given",
   [r["title"] for r in ROWS["AI"]], ["A first", "A second", "A third"])
eq("nothing anywhere means no prompt at all",
   summarize.build_prompt({"AI": [], "Rust": []}, LABELS, max_per_topic=2), "")


# --- the happy path -------------------------------------------------------

text = summarize.summarize(fetcher, url("/ok"), "sk-test", "gpt-4o-mini",
                           ROWS, LABELS, max_per_topic=2)
eq("the summary comes back stripped",
   text, "AI — Có hai bài đáng đọc.\nRust — Bản 1.9 ra.")
eq("...in exactly one request", HITS.get("/ok"), 1)
eq("...carrying the bearer token",
   SEEN_HEADERS["/ok"].get("Authorization"), "Bearer sk-test")

sent = json.loads(SEEN_BODIES["/ok"])
eq("...and the configured model", sent.get("model"), "gpt-4o-mini")
check("...and the prompt as a chat message",
      any("A first" in (m.get("content") or "")
          for m in sent.get("messages") or []), sent)


# --- every way it can go wrong, and none of them raises -------------------

HITS.clear()

eq("a 500 is a missing summary, not an exception",
   summarize.summarize(fetcher, url("/500"), "k", "m", ROWS, LABELS, 2), None)
eq("a 200 that is not JSON is a missing summary",
   summarize.summarize(fetcher, url("/not-json"), "k", "m", ROWS, LABELS, 2),
   None)
eq("a JSON body with no choices is a missing summary",
   summarize.summarize(fetcher, url("/empty-json"), "k", "m", ROWS, LABELS, 2),
   None)
eq("a choice with no content is a missing summary",
   summarize.summarize(fetcher, url("/no-content"), "k", "m", ROWS, LABELS, 2),
   None)
eq("a refused connection is a missing summary",
   summarize.summarize(fetcher, "http://127.0.0.1:1/v1", "k", "m", ROWS,
                       LABELS, 2), None)

# The two short-circuits. Both must cost nothing at all - no request, and so no
# bill for asking a question with no content in it.
HITS.clear()
eq("no key means no summary", summarize.summarize(
    fetcher, url("/ok"), "", "m", ROWS, LABELS, 2), None)
eq("no url means no summary", summarize.summarize(
    fetcher, "", "k", "m", ROWS, LABELS, 2), None)
eq("a day with no story means no summary", summarize.summarize(
    fetcher, url("/ok"), "k", "m", {"AI": []}, LABELS, 2), None)
eq("...and none of the three sent a request", sum(HITS.values()), 0)


server.shutdown()

# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
