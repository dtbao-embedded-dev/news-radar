#!/usr/bin/env python3
"""Checks for src/news_radar/notify/ - plain asserts, no test framework.

    python tests/test_notify.py

Standard library only, and it never leaves the machine: a local http.server
plays the bot API and the webhook, including the answers that must not be
retried. `build()` is pure on both channels, so every escaping and splitting
rule is checked without a socket at all.
"""

from __future__ import annotations

import http.server
import json
import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar import notify  # noqa: E402
from news_radar.fetch.http import Fetcher  # noqa: E402
from news_radar.notify import discord, telegram  # noqa: E402

FAILURES = []
HITS = {}
BODIES = {}


def check(name, condition, detail=""):
    if not condition:
        FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def eq(name, got, want):
    check(name, got == want, "got {!r}, want {!r}".format(got, want))


def row(title, key, url="https://example.com/a", sources=("hn",)):
    """The shape `store.run_matches()` hands back, and nothing more."""
    return {"dedup_key": key, "title": title, "url": url,
            "canonical_url": url, "score": 0.9, "published_at": None,
            "first_seen_at": None, "sources": sources}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        path = self.path
        HITS[path] = HITS.get(path, 0) + 1
        BODIES.setdefault(path, []).append(json.loads(self.rfile.read(
            int(self.headers.get("Content-Length") or 0))))

        if "bad" in path:
            self._reply(400, b'{"message":"Invalid Webhook Token","code":50027}')
            return
        if "flaky" in path and HITS[path] > 1:
            self._reply(400, b'{"ok":false,"description":"too many entities"}')
            return
        if path.startswith("/webhook"):
            # Discord answers a webhook with 204 and no body at all - not the
            # 200 + JSON the bot API sends.
            self.send_response(204)
            self.end_headers()
            return
        self._reply(200, b'{"ok":true}')

    def _reply(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
PORT = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()

telegram.API = "http://127.0.0.1:{}/bot{{token}}/sendMessage".format(PORT)

UA = "news-radar/9.9.9 (+https://news.dtbao.org)"
fetcher = Fetcher(user_agent=UA, timeout_s=5, max_retries=1, backoff_s=0.01,
                  interval_ms=0)


# --- pick: the group order, and the seen-set diff --------------------------

# The store returns a mapping; the keyword file fixes the order. Rendering the
# mapping's own order would shuffle the sections between runs.
BY_LABEL = {"Rust": [row("R1", "r1"), row("R2", "r2")],
            "ESP32": [row("E1", "e1")],
            "Quiet": []}
LABELS = ["ESP32", "Rust", "Quiet", "Never"]

picked = notify.pick(BY_LABEL, LABELS)
eq("the keyword file's order wins, not the mapping's",
   [label for label, _ in picked], ["ESP32", "Rust"])
eq("a group with nothing in it is dropped, not sent empty",
   [label for label, _ in picked], ["ESP32", "Rust"])
eq("every row of a kept group travels", len(picked[1][1]), 2)

# The diff. `keys` is what the seen-set said is still unsent on this channel.
diffed = notify.pick(BY_LABEL, LABELS, {"r2"})
eq("only the unsent stories survive the diff",
   [(label, [r["dedup_key"] for r in rows]) for label, rows in diffed],
   [("Rust", ["r2"])])
eq("a group emptied by the diff disappears with it", len(diffed), 1)
eq("nothing unsent means nothing at all - not an empty message",
   notify.pick(BY_LABEL, LABELS, set()), [])
eq("an empty key set is not the same as no diff at all",
   len(notify.pick(BY_LABEL, LABELS, None)), 2)


# --- the shared chunker ---------------------------------------------------

# Two small groups belong in one message; the split exists for size, not for
# tidiness, and one notification beats two.
one = notify.chunk([("A", [("a1", "k1"), ("a2", "k2")]),
                    ("B", [("b1", "k3")])], 4000)
eq("small groups travel in one message", len(one), 1)
eq("every key of every group is carried", one[0][1], ("k1", "k2", "k3"))
check("a group boundary is a blank line", "\n\n" in one[0][0], repr(one[0][0]))

# A group that does not fit is split at an item boundary, and the header is
# repeated so the second message is readable on its own.
big = notify.chunk([("HEADER", [("x" * 40, "k{}".format(i))
                                for i in range(10)])], 120)
check("an oversized group is split", len(big) > 1, str(len(big)))
check("every part is under the limit",
      all(len(text) <= 120 for text, _ in big),
      str([len(t) for t, _ in big]))
check("the header is repeated on every part",
      all(text.startswith("HEADER") for text, _ in big))
check("no story is cut in half",
      all(line in ("HEADER", "x" * 40)
          for text, _ in big for line in text.split("\n")))
keys = [k for _, ks in big for k in ks]
eq("no story is lost to the split", len(keys), 10)
eq("no story is sent twice by the split", len(set(keys)), 10)

# The page prints "Security - 0 item(s)" because a reader is looking for the
# keyword that went quiet. A push notification saying nothing happened is spam.
eq("an empty group contributes nothing", notify.chunk([("Quiet", [])], 4000), [])
eq("nothing at all sends nothing", notify.chunk([], 4000), [])

eq("a short title is left alone", notify.clip("short"), "short")
long_title = "x" * 500
clipped = notify.clip(long_title)
eq("a long title is clipped to the cap", len(clipped), notify.TITLE_MAX)
check("...and says so", clipped.endswith("…"))


# --- telegram: what a feed title may not do to a message ------------------

hostile = telegram.build([("ESP32", [
    row('<script>alert(1)</script> & "quotes"', "k1")])])
text = hostile[0][0]
check("a tag in a title is escaped", "&lt;script&gt;" in text, text)
check("no raw tag survives", "<script>" not in text, text)
check("an ampersand is escaped, or Telegram drops the whole message",
      "&amp;" in text, text)
check("the group label is a bold tag", text.startswith("<b>ESP32</b>"), text)
check("the link is a real anchor", '<a href="https://example.com/a">' in text)
check("the sources travel with the story", "<i>hn</i>" in text, text)

quoted = telegram.build([("G", [row("t", "k", url='https://x/?a="b"')])])[0][0]
check("a quote in a url cannot break out of href",
      '"' not in quoted.split('href="')[1].split('"')[0], quoted)


# --- telegram: the wire ---------------------------------------------------

groups = [("ESP32", [row("First", "k1"), row("Second", "k2")]),
          ("Rust", [row("Third", "k3")])]

result = telegram.send(fetcher, groups, "TOKEN", "-100123")
eq("one message went out", result.sent, 1)
eq("nothing failed", result.failed, 0)
eq("the accepted keys come back for mark_reported", set(result.keys),
   {"k1", "k2", "k3"})
eq("the result counts stories, not chunks", result.stories, 3)

body = BODIES["/botTOKEN/sendMessage"][0]
eq("the chat id is sent as configured", body["chat_id"], "-100123")
eq("HTML is the declared parse mode", body["parse_mode"], "HTML")
eq("link previews are off - one preview would bury the list",
   body["disable_web_page_preview"], True)
check("the message carries both groups",
      "ESP32" in body["text"] and "Rust" in body["text"])

eq("nothing to send posts nothing at all",
   telegram.send(fetcher, [], "TOKEN", "-100123").sent, 0)
eq("...and asks the API nothing", HITS.get("/botTOKEN/sendMessage"), 1)

# A bad token or a bad chat id answers the same way however many times it is
# asked. Retrying it costs the run three requests for one answer.
bad = telegram.send(fetcher, groups, "-bad", "-100123")
eq("a refused channel sends nothing", bad.sent, 0)
eq("a refused channel is recorded as failed", bad.failed, 1)
eq("a refused channel marks no story as reported", bad.keys, ())
eq("a 400 is not retried", HITS.get("/bot-bad/sendMessage"), 1)

# Half a run delivered is still half a run delivered: those stories must not be
# pushed again tomorrow, and the rest must.
many = [("G{}".format(i), [row("x" * 300, "k{}".format(i))]) for i in range(40)]
check("the fixture is big enough to need two messages",
      len(telegram.build(many)) > 1, str(len(telegram.build(many))))
partial = telegram.send(fetcher, many, "-flaky", "-100123")
eq("the accepted chunk still counts", partial.sent, 1)
eq("the refused one is counted too", partial.failed, 1)
check("only the accepted stories come back for marking",
      0 < len(partial.keys) < 40, str(len(partial.keys)))


# --- discord: markdown is a second escaping problem, not the same one -----

WEBHOOK = "http://127.0.0.1:{}/webhook".format(PORT)

hostile_md = discord.build([("ESP32", [
    row("*bold* _under_ [link] `code` ~strike~ |spoil|", "k1")])])
md = hostile_md[0][0]
check("the group label is bold markdown", md.startswith("**ESP32**"), md)
check("a bracket in a title cannot break the link syntax",
      "\\[link\\]" in md, md)
check("an asterisk in a title is escaped", "\\*bold\\*" in md, md)
check("an underscore in a title is escaped", "\\_under\\_" in md, md)
check("a backtick in a title is escaped", "\\`code\\`" in md, md)
check("a tilde in a title is escaped", "\\~strike\\~" in md, md)
check("a pipe in a title is escaped", "\\|spoil\\|" in md, md)
check("the story is a masked link, so the raw url never widens the line",
      "](https://example.com/a)" in md, md)

paren = discord.build([("G", [row("t", "k", url="https://x/a(b)c")])])[0][0]
check("a closing paren in a url is encoded, not left to end the link early",
      "%29" in paren and "(b)" not in paren, paren)

# 2000 is a quarter of Telegram's budget: the same run makes more Discord
# messages than Telegram messages, which is expected rather than a bug.
same = [("G{}".format(i), [row("x" * 200, "k{}-{}".format(i, j))
                           for j in range(4)]) for i in range(6)]
check("a quarter of the budget makes more messages, not truncated ones",
      len(discord.build(same)) > len(telegram.build(same)),
      "{} vs {}".format(len(discord.build(same)), len(telegram.build(same))))
check("every discord chunk is under the webhook limit",
      all(len(text) <= discord.LIMIT for text, _ in discord.build(same)))

dgroups = [("ESP32", [row("First", "k1"), row("Second", "k2")]),
           ("Rust", [row("Third", "k3")])]

dres = discord.send(fetcher, dgroups, WEBHOOK)
eq("one webhook post went out", dres.sent, 1)
eq("nothing failed", dres.failed, 0)
eq("the accepted keys come back for mark_reported", set(dres.keys),
   {"k1", "k2", "k3"})

dbody = BODIES["/webhook"][0]
check("the payload is a plain content body", "content" in dbody, str(dbody))
check("no embeds - the 6000-character total is easier to overrun than the "
      "per-embed limit", "embeds" not in dbody, str(dbody))
check("the message carries both groups",
      "ESP32" in dbody["content"] and "Rust" in dbody["content"])

eq("nothing to send posts nothing at all",
   discord.send(fetcher, [], WEBHOOK).sent, 0)
eq("...and asks the webhook nothing", HITS.get("/webhook"), 1)

dbad = discord.send(fetcher, dgroups, WEBHOOK + "-bad")
eq("a revoked webhook sends nothing", dbad.sent, 0)
eq("a revoked webhook is recorded as failed", dbad.failed, 1)
eq("a revoked webhook marks no story as reported", dbad.keys, ())
eq("a 400 is not retried", HITS.get("/webhook-bad"), 1)


server.shutdown()

# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f_ in FAILURES:
        print("  - {}".format(f_))
    sys.exit(1)

print("OK")
