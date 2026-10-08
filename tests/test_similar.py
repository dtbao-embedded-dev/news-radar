#!/usr/bin/env python3
"""Checks for src/news_radar/similar.py - plain asserts, no test framework.

    python tests/test_similar.py

Standard library only, and it never leaves the machine: a local http.server
plays an OpenAI-compatible `/v1/embeddings`, including every way one goes
wrong. The vectors it hands back are small and hand-made, so what is being
checked is the contract - order, normalising, failing quietly - and not any
model's idea of which headlines are alike.
"""

from __future__ import annotations

import http.server
import json
import math
import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar import similar  # noqa: E402
from news_radar.fetch.http import Fetcher  # noqa: E402

FAILURES = []
HITS = {}
BODIES = {}


def check(name, condition, detail=""):
    if not condition:
        FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def eq(name, got, want):
    check(name, got == want, "got {!r}, want {!r}".format(got, want))


def close(a, b):
    return all(abs(x - y) < 1e-9 for x, y in zip(a, b)) and len(a) == len(b)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        path = self.path
        HITS[path] = HITS.get(path, 0) + 1
        body = json.loads(self.rfile.read(
            int(self.headers.get("Content-Length") or 0)) or b"{}")
        BODIES[path] = body
        texts = body.get("input") or []

        if path == "/ok":
            # Answered out of order on purpose: `index` is the contract, and an
            # endpoint is allowed to return the list in whatever order it likes.
            data = [{"index": i, "embedding": [3.0, 4.0] if i % 2 == 0
                     else [0.0, 2.0]} for i in range(len(texts))]
            self._reply(200, {"data": list(reversed(data))})
        elif path == "/short":
            self._reply(200, {"data": [{"index": 0, "embedding": [1.0, 0.0]}]})
        elif path == "/zero":
            self._reply(200, {"data": [{"index": i, "embedding": [0.0, 0.0]}
                                       for i in range(len(texts))]})
        elif path == "/missing-model":
            self._reply(404, {"error": {"message": "model not found, try pulling it first"}})
        elif path == "/html":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html>gateway timeout</html>")
        else:
            self._reply(500, {"error": "upstream is having a day"})

    def _reply(self, status, payload):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:{}".format(server.server_address[1])
fetcher = Fetcher(user_agent="news-radar-test", timeout_s=5, max_retries=0,
                  interval_ms=0)


def row(title, key):
    return {"title": title, "dedup_key": key}


# --- embed(): one request, vectors in the caller's order, unit length -------

got = similar.embed(fetcher, BASE + "/ok", "all-minilm", ["a", "b", "c"])
eq("one vector per text", len(got or []), 3)
check("vectors come back in input order whatever order the endpoint used",
      close(got[0], [0.6, 0.8]) and close(got[1], [0.0, 1.0])
      and close(got[2], [0.6, 0.8]), repr(got))
check("every vector is unit length, so a dot product is the cosine",
      all(abs(math.hypot(*v) - 1.0) < 1e-9 for v in got), repr(got))
eq("the whole batch is one request", HITS.get("/ok"), 1)
eq("the request names the model and carries the texts",
   (BODIES["/ok"].get("model"), BODIES["/ok"].get("input")),
   ("all-minilm", ["a", "b", "c"]))

HITS.clear()
eq("no texts, no request", similar.embed(fetcher, BASE + "/ok", "m", []), [])
eq("and nothing was asked", HITS, {})

# Every failure is the same answer: None, and the caller falls back to Jaccard.
for path in ("/500", "/missing-model", "/html", "/short"):
    eq("{} is no vectors, not an exception".format(path),
       similar.embed(fetcher, BASE + path, "m", ["a", "b"]), None)

# A zero vector has no direction. Normalising it would divide by zero, and
# keeping it would make it "similar" to nothing and everything at once.
eq("a zero vector is a failed answer",
   similar.embed(fetcher, BASE + "/zero", "m", ["a"]), None)

eq("an empty url never asks",
   similar.embed(fetcher, "", "m", ["a"]), None)


# --- vectors(): rows -> {dedup_key: vector}, one request per cycle ----------

HITS.clear()
rows = [row("ESP32-C6 board ships with Thread - cnx-software.com", "k1"),
        row("Totally different story", "k2"),
        row("ESP32-C6 board ships with Thread - cnx-software.com", "k1")]  # twice
got = similar.vectors(fetcher, BASE + "/ok", "all-minilm", rows)
eq("one vector per distinct story", sorted(got), ["k1", "k2"])
eq("a story claimed by two groups is embedded once",
   BODIES["/ok"]["input"], ["esp32 c6 board ships with thread", "totally different story"])
eq("still one request", HITS.get("/ok"), 1)

eq("an endpoint that fails is an empty map",
   similar.vectors(fetcher, BASE + "/500", "m", rows), {})
eq("no rows is an empty map", similar.vectors(fetcher, BASE + "/ok", "m", []), {})


# --------------------------------------------------------------------------

server.shutdown()
if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for failure in FAILURES:
        print("  - " + failure)
    sys.exit(1)
print("OK")
