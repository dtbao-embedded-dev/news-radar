#!/usr/bin/env python3
"""Checks for src/news_radar/__main__.py - plain asserts, no test framework.

    python tests/test_main.py

Needs feedparser and PyYAML. Two pieces of the wiring that no module below it
can see: the schedule loop's cadence, and how the channels are driven. Every
collaborator is replaced - `crawl()`, the stop event, the senders - so nothing
here touches the network.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar import __main__ as mod  # noqa: E402
from news_radar import config as cfgmod  # noqa: E402
from news_radar import store  # noqa: E402
from news_radar.item import dedup_key, new_item  # noqa: E402
from news_radar.notify import SendResult  # noqa: E402
from news_radar.rank import Story  # noqa: E402

FAILURES = []
NOW = dt.datetime(2026, 10, 6, 12, 0, tzinfo=dt.timezone.utc)


def check(name, condition, detail=""):
    if not condition:
        FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def eq(name, got, want):
    check(name, got == want, "got {!r}, want {!r}".format(got, want))


# --- run(): the interval is start to start, not end to start ---------------

class FakeStop:
    """The stop event, recording every wait and ending the loop after `cycles`."""

    def __init__(self, cycles):
        self.cycles = cycles
        self.waits = []

    def is_set(self):
        return len(self.waits) >= self.cycles

    def wait(self, seconds):
        self.waits.append(seconds)
        return self.is_set()


def run_with(cycle_s, interval_minutes, cycles=1):
    stop = FakeStop(cycles)
    real_stop, real_crawl = mod._stop, mod.crawl

    def crawl(_cfg):
        time.sleep(cycle_s)
        return {}, []

    mod._stop, mod.crawl = stop, crawl
    try:
        mod.run(cfgmod.Config({"schedule": {"interval_minutes": interval_minutes}}))
    finally:
        mod._stop, mod.crawl = real_stop, real_crawl
    return stop.waits


# A 30-minute interval measured from the *end* of a two-minute cycle is a
# 32-minute period: the runs drift later all day and the day gets fewer of
# them than the config says.
waits = run_with(cycle_s=0.3, interval_minutes=1)
# The cycle sleeps 0.3 s, so the wait is about 59.7 s at most (sleep may wake a
# few ms early on Windows, hence 59.75); the lower bound is
# loose on purpose, a loaded CI runner may take far longer than 0.3 s.
check("the wait is the interval minus the time the cycle took",
      len(waits) == 1 and 50.0 <= waits[0] <= 59.75, repr(waits))

# A cycle longer than its interval starts the next one at once - a negative
# wait is not a wait, and skipping a beat to "catch up" would lose a cycle.
waits = run_with(cycle_s=0.05, interval_minutes=0.0005)  # a 0.03 s interval
eq("an overrunning cycle is followed immediately", waits, [0])


# --- _notify(): the channels are sent side by side -------------------------

def story(title):
    item = new_item(title=title, url="https://example.com/" + title.replace(" ", "-"),
                    source_id="hn", fetched_at=NOW, published_at=NOW)
    return Story(item=item, source_ids=("hn",), labels=("ESP32",),
                 published_at=NOW, score=0.5)


tmp = tempfile.mkdtemp(prefix="news-radar-main-")
conn = store.open_db(tmp)
run_id = store.start_run(conn, NOW)
stories = [story("ESP32 board one"), story("ESP32 board two")]
store.save(conn, run_id, {"ESP32": stories}, NOW)
conn.close()
KEYS = [dedup_key(s.item) for s in stories]

NOTIFY = {
    "advanced": {"user_agent": "news-radar-test"},
    "report": {"mode": "incremental"},
    "notification": {"channels": {"telegram": {"enabled": True},
                                  "discord": {"enabled": True}}},
}
notify_cfg = cfgmod.Config(dict(NOTIFY, storage={"data_dir": tmp}))

SPANS = {}


def fake_sender(name, fail=False):
    """A channel that takes 0.3 s per cycle, like two rate-limited messages."""

    def send(fetcher, groups, env, tz):
        start = time.monotonic()
        time.sleep(0.3)
        SPANS[name] = (start, time.monotonic(), threading.current_thread().name)
        if fail:
            raise RuntimeError("{} is down".format(name))
        keys = tuple(row["dedup_key"] for _, rows in groups for row in rows)
        return SendResult(sent=len(keys), keys=keys)

    return send


real_senders = dict(mod.SENDERS)
mod.SENDERS.update(telegram=fake_sender("telegram"), discord=fake_sender("discord"))
try:
    mod._notify(notify_cfg, run_id, ["ESP32"], {"ESP32": 0}, NOW)
finally:
    mod.SENDERS.clear()
    mod.SENDERS.update(real_senders)

# Two channels are two hosts with two rate limits. Sending one after the other
# makes a busy cycle wait out Telegram's gaps and then Discord's in full.
check("both channels were sent", set(SPANS) == {"telegram", "discord"}, repr(SPANS))
check("and they overlapped rather than queued",
      SPANS["telegram"][0] < SPANS["discord"][1]
      and SPANS["discord"][0] < SPANS["telegram"][1], repr(SPANS))
# The overlap above is the property. A wall-clock bound on the whole call was
# here too and failed on a loaded CI runner (0.95 s) while the overlap held:
# opening the store and starting threads are not this test's business.

conn = store.open_db(tmp)
for channel in ("telegram", "discord"):
    eq("every accepted story is marked on {}".format(channel),
       store.unreported(conn, KEYS, channel), [])
conn.close()

# One channel raising must not cost the other its send or its marks.
tmp2 = tempfile.mkdtemp(prefix="news-radar-main-")
conn = store.open_db(tmp2)
run_id2 = store.start_run(conn, NOW)
store.save(conn, run_id2, {"ESP32": stories}, NOW)
conn.close()
SPANS.clear()
mod.SENDERS.update(telegram=fake_sender("telegram", fail=True),
                   discord=fake_sender("discord"))
try:
    mod._notify(cfgmod.Config(dict(NOTIFY, storage={"data_dir": tmp2})),
                run_id2, ["ESP32"], {"ESP32": 0}, NOW)
finally:
    mod.SENDERS.clear()
    mod.SENDERS.update(real_senders)

conn = store.open_db(tmp2)
eq("a channel that raised marks nothing",
   store.unreported(conn, KEYS, "telegram"), KEYS)
eq("and the other channel still sent and marked",
   store.unreported(conn, KEYS, "discord"), [])
conn.close()


# --- _notify(): headline vectors reach the clustering ----------------------

def paraphrase_store():
    """Two write-ups of one event that share too few words to cluster."""
    path = tempfile.mkdtemp(prefix="news-radar-main-")
    db = store.open_db(path)
    rid = store.start_run(db, NOW)
    pair = [story("Meta and Microsoft limit employee use of Claude tools"),
            story("Big tech firms take steps to reduce staff usage of an assistant")]
    store.save(db, rid, {"ESP32": pair}, NOW)
    db.close()
    return path, rid, [dedup_key(s.item) for s in pair]


def recording_sender():
    def send(fetcher, groups, env, tz):
        keys = tuple(row["dedup_key"] for _, rows in groups for row in rows)
        SENT.append(keys)
        return SendResult(sent=len(keys), keys=keys)
    return send


# `Config()` straight from a dict skips `load()`'s defaults, so the section is
# spelled out in full here.
SIMILAR_ON = dict(NOTIFY, similar={"enabled": True, "threshold": 0.75,
                                   "api_url": "http://ollama:11434/v1/embeddings",
                                   "model": "all-minilm"},
                  notification={"channels": {"telegram": {"enabled": True},
                                             "discord": {"enabled": False}}})
ASKED = []


def fake_vectors(answer):
    def vectors(fetcher, api_url, model, rows):
        ASKED.append((api_url, model, sorted(r["dedup_key"] for r in rows)))
        return answer(rows)
    return vectors


real_vectors = mod.similar.vectors
for name, answer, want in (
        ("close vectors send one message for the event",
         lambda rows: {r["dedup_key"]: [1.0, 0.0] for r in rows}, 1),
        ("an endpoint that failed clusters on words alone",
         lambda rows: {}, 2)):
    path, rid, keys = paraphrase_store()
    SENT, ASKED[:] = [], []
    mod.SENDERS.update(telegram=recording_sender())
    mod.similar.vectors = fake_vectors(answer)
    try:
        mod._notify(cfgmod.Config(dict(SIMILAR_ON, storage={"data_dir": path})),
                    rid, ["ESP32"], {"ESP32": 0}, NOW)
    finally:
        mod.similar.vectors = real_vectors
        mod.SENDERS.clear()
        mod.SENDERS.update(real_senders)
    eq(name, [len(k) for k in SENT], [want])
    eq("the vectors are asked once a cycle, for every row: " + name,
       ASKED, [("http://ollama:11434/v1/embeddings", "all-minilm", sorted(keys))])

# Off is the shipped case, and off never asks.
path, rid, keys = paraphrase_store()
SENT, ASKED[:] = [], []
mod.SENDERS.update(telegram=recording_sender())
mod.similar.vectors = fake_vectors(lambda rows: {})
try:
    off = dict(SIMILAR_ON, similar={"enabled": False})
    mod._notify(cfgmod.Config(dict(off, storage={"data_dir": path})),
                rid, ["ESP32"], {"ESP32": 0}, NOW)
finally:
    mod.similar.vectors = real_vectors
    mod.SENDERS.clear()
    mod.SENDERS.update(real_senders)
eq("similar off never asks for vectors", ASKED, [])
eq("and sends both write-ups, as before", [len(k) for k in SENT], [2])


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
