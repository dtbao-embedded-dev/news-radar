#!/usr/bin/env python3
"""Checks for src/news_radar/summarize.py - plain asserts, no test framework.

    python tests/test_summarize.py

Standard library only, and it never leaves the machine: a local http.server
plays the OpenAI-compatible endpoint, including every way it can answer badly.

Three rules this file exists to pin:

- **The prompt is per story, numbered, and carries the source's own words.**
  The number is the only thing mapping an answer back onto a row, so it is the
  one thing the parser must never get wrong.
- **Every row asked about comes back with an entry.** A row the model skipped
  maps to `""`, which the store writes as "asked, nothing useful" - otherwise
  one skipped line costs a completion every thirty minutes forever.
- **A summary is optional, so nothing here may raise.** Every failure the wire
  and a strange body can produce comes back as `{}` and one log line.
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

ANSWER = ("  1. Bài về SDK mới cho ESP32-S3.\n"
          "2. Nguồn điện trên board dev.\n"
          "3. Rust vào nhân Linux.  ")


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
        if path == "/chatty":
            # The failure mode every model has: a preamble, a skipped line, a
            # number that belongs to no story, and its own idea of bullets.
            self._reply(200, self._content(
                "Đây là tóm tắt hôm nay:\n\n"
                "- **1.** Bài về SDK mới cho ESP32-S3.\n"
                "3) Rust vào nhân Linux.\n"
                "9. Một bài không tồn tại.\n"))
            return
        self._reply(200, self._content(ANSWER))

    @staticmethod
    def _content(text):
        return json.dumps({
            "choices": [{"message": {"role": "assistant", "content": text}}],
        }).encode("utf-8")

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


def row(key, title, excerpt=""):
    return {"dedup_key": key, "title": title, "url": "https://e.invalid/x",
            "excerpt": excerpt, "ai_summary": "", "score": 1.0,
            "sources": ("hn",)}


ROWS = [
    row("k1", "ESP32-S3 SDK 5.5", "Espressif ships a new SDK with USB fixes."),
    row("k2", "ESP32 power rails"),
    row("k3", "Rust in the kernel", "Linux 6.20 merges the Rust bindings."),
]


# --- build_prompt: pure, ordered, numbered --------------------------------

prompt = summarize.build_prompt(ROWS)

check("every title reaches the prompt",
      all(r["title"] in prompt for r in ROWS), prompt)
check("the source's own description reaches it too",
      "Espressif ships a new SDK" in prompt, prompt)
check("the rows are numbered from one, in the caller's order",
      prompt.index("1. ESP32-S3") < prompt.index("2. ESP32 power")
      < prompt.index("3. Rust in"), prompt)
check("a row with no description is still in, on its title alone",
      "2. ESP32 power rails" in prompt, prompt)
check("the instruction asks for Vietnamese", "Vietnamese" in prompt, prompt)
check("the instruction bounds the sentences per story",
      str(summarize.SENTENCES_MAX) in prompt, prompt)

long_row = row("k9", "A title", "x" * 5000)
check("an enormous excerpt is cut before it is paid for",
      len(summarize.build_prompt([long_row])) < len(summarize.INSTRUCTION) + 600,
      str(len(summarize.build_prompt([long_row]))))

eq("build_prompt does not mutate the rows it was given",
   [r["title"] for r in ROWS],
   ["ESP32-S3 SDK 5.5", "ESP32 power rails", "Rust in the kernel"])
eq("no rows means no prompt at all", summarize.build_prompt([]), "")


# --- parse_answer: the number is the only thing that has to be right ------

parsed = summarize.parse_answer(ANSWER, ROWS)
eq("one entry per row, keyed by dedup_key", sorted(parsed), ["k1", "k2", "k3"])
eq("the sentence lands on the row its number names",
   parsed["k1"], "Bài về SDK mới cho ESP32-S3.")
eq("...and so does the last one", parsed["k3"], "Rust vào nhân Linux.")

messy = summarize.parse_answer(
    "Đây là tóm tắt:\n\n- **1.** Một.\n3) Ba.\n9. Không tồn tại.\n", ROWS)
eq("a bulleted, bolded number is still a number", messy["k1"], "Một.")
eq("a closing paren is a separator too", messy["k3"], "Ba.")
eq("a skipped row comes back empty rather than missing", messy["k2"], "")
check("a number outside the batch is dropped, not clamped onto a real story",
      "Không tồn tại" not in "".join(messy.values()), messy)

runaway = summarize.parse_answer("1. " + "từ " * 400, ROWS)
check("a model that writes a paragraph is cut to the cap",
      len(runaway["k1"]) <= summarize.SUMMARY_MAX + 1, len(runaway["k1"]))

eq("a repeated number keeps the first line, where the answer is",
   summarize.parse_answer("1. Đúng.\n1. Ghi chú thêm.", ROWS)["k1"], "Đúng.")
eq("an answer with no numbers at all leaves every row empty",
   set(summarize.parse_answer("Hôm nay không có gì.", ROWS).values()), {""})


# --- the happy path -------------------------------------------------------

got = summarize.summarize(fetcher, url("/ok"), "sk-test", "gpt-4o-mini", ROWS)
eq("every row comes back with a sentence",
   got, {"k1": "Bài về SDK mới cho ESP32-S3.",
         "k2": "Nguồn điện trên board dev.",
         "k3": "Rust vào nhân Linux."})
eq("...in exactly one request for the whole batch", HITS.get("/ok"), 1)
eq("...carrying the bearer token",
   SEEN_HEADERS["/ok"].get("Authorization"), "Bearer sk-test")

sent = json.loads(SEEN_BODIES["/ok"])
eq("...and the configured model", sent.get("model"), "gpt-4o-mini")
check("...and the prompt as a chat message",
      any("ESP32-S3 SDK 5.5" in (m.get("content") or "")
          for m in sent.get("messages") or []), sent)

chatty = summarize.summarize(fetcher, url("/chatty"), "k", "m", ROWS)
eq("a chatty model still costs one request", HITS.get("/chatty"), 1)
eq("...and the rows it answered are the rows that get a sentence",
   chatty, {"k1": "Bài về SDK mới cho ESP32-S3.", "k2": "",
            "k3": "Rust vào nhân Linux."})


# --- every way it can go wrong, and none of them raises -------------------

# `{}` rather than a mapping of empty strings: a failed *request* must leave
# the stories unasked so the next cycle tries them again, while a request that
# was answered and skipped a line marks that story done.
HITS.clear()

eq("a 500 is no summary, not an exception",
   summarize.summarize(fetcher, url("/500"), "k", "m", ROWS), {})
eq("a 200 that is not JSON is no summary",
   summarize.summarize(fetcher, url("/not-json"), "k", "m", ROWS), {})
eq("a JSON body with no choices is no summary",
   summarize.summarize(fetcher, url("/empty-json"), "k", "m", ROWS), {})
eq("a choice with no content is no summary",
   summarize.summarize(fetcher, url("/no-content"), "k", "m", ROWS), {})
eq("a refused connection is no summary",
   summarize.summarize(fetcher, "http://127.0.0.1:1/v1", "k", "m", ROWS), {})


# --- no key is a supported deployment, not a failure ----------------------

# An SGLang, vLLM or Ollama on the LAN authenticates nobody. Sending
# `Authorization: Bearer ` to one is at best ignored and at worst a 401 from
# whatever sits in front of it, so the header is simply not sent.
HITS.clear()
check("a keyless endpoint still returns summaries",
      summarize.summarize(fetcher, url("/noauth"), "", "m", ROWS))
eq("...and it was actually asked", HITS.get("/noauth"), 1)
check("...with no Authorization header at all",
      "Authorization" not in SEEN_HEADERS["/noauth"],
      SEEN_HEADERS["/noauth"])

check("a key of whitespace is treated as no key",
      summarize.summarize(fetcher, url("/blank-key"), "   ", "m", ROWS))
check("...and sends no header either",
      "Authorization" not in SEEN_HEADERS["/blank-key"],
      SEEN_HEADERS["/blank-key"])

# The two short-circuits. Both must cost nothing at all - no request, and so no
# bill for asking a question with no content in it.
HITS.clear()
eq("no url means no summary",
   summarize.summarize(fetcher, "", "k", "m", ROWS), {})
eq("a cycle with no new story means no summary",
   summarize.summarize(fetcher, url("/ok"), "k", "m", []), {})
eq("...and neither sent a request", sum(HITS.values()), 0)


server.shutdown()

# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
