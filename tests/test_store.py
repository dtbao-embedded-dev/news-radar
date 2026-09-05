#!/usr/bin/env python3
"""Checks for src/news_radar/store.py - plain asserts, no test framework.

    python tests/test_store.py

Standard library only: `sqlite3` ships with Python, and `store.py` imports no
config and reads no clock, so every timestamp below is fixed and every
assertion about ordering, windows and retention is exact rather than
approximate.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar import store as mod  # noqa: E402
from news_radar.item import dedup_key, new_item  # noqa: E402
from news_radar.rank import Story  # noqa: E402

FAILURES = []
TMP = pathlib.Path(tempfile.mkdtemp(prefix="news-radar-store-"))
COUNTER = [0]

NOW = dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.timezone.utc)
HOUR = dt.timedelta(hours=1)
DAY = dt.timedelta(days=1)


def check(name, condition, detail=""):
    if not condition:
        FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def eq(name, got, want):
    check(name, got == want, "got {!r}, want {!r}".format(got, want))


def data_dir():
    COUNTER[0] += 1
    return TMP / "run{}".format(COUNTER[0])


def item(title, url, source_id, published_at=None):
    return new_item(title, url, source_id, NOW, published_at=published_at)


def story(it, labels, sources=None, published_at=None, score=1.0):
    return Story(item=it, source_ids=tuple(sources or (it.source_id,)),
                 labels=tuple(labels),
                 published_at=published_at if published_at is not None
                 else it.published_at,
                 score=score)


def counts(conn, table):
    return conn.execute("SELECT count(*) FROM {}".format(table)).fetchone()[0]


# -- open_db: the directory, the schema, the migration ----------------------

root = data_dir()
conn = mod.open_db(root)

check("open_db creates the data directory", root.is_dir())
check("open_db creates news.db inside it", (root / "news.db").is_file())
eq("a fresh store is at the current schema version",
   conn.execute("PRAGMA user_version").fetchone()[0], mod.SCHEMA_VERSION)

tables = {r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")}
eq("every table the contract names exists",
   {"items", "item_sources", "matches", "reported", "runs"} - tables, set())

run_id = mod.start_run(conn, NOW)
check("start_run returns an id", bool(run_id))
eq("start_run writes exactly one row", counts(conn, "runs"), 1)
conn.close()

# Reopening must not re-run the migration: a second CREATE would either fail or
# silently empty the store, and the whole point of P3 is that a restart keeps
# what the morning found.
conn = mod.open_db(root)
eq("reopening keeps the schema version", conn.execute(
    "PRAGMA user_version").fetchone()[0], mod.SCHEMA_VERSION)
eq("reopening keeps the rows already written", counts(conn, "runs"), 1)
conn.close()


# -- save: the shape one run writes ----------------------------------------

conn = mod.open_db(data_dir())
r1 = mod.start_run(conn, NOW)

esp = item("ESP32-S3 gets a new SDK", "https://example.com/esp32", "hn",
           published_at=NOW - HOUR)
quiet = item("Rust in the kernel", "https://example.com/rust", "lobsters")

written = mod.save(conn, r1, {
    "ESP32": [story(esp, ["ESP32"], score=0.91)],
    "Rust": [story(quiet, ["Rust"], score=0.42)],
    "Security": [],
}, NOW)

eq("save reports the number of match rows it wrote", written, 2)
eq("one items row per distinct story", counts(conn, "items"), 2)
eq("one matches row per (story, group)", counts(conn, "matches"), 2)
eq("an empty group writes nothing", counts(conn, "item_sources"), 2)

row = conn.execute("SELECT * FROM items WHERE dedup_key=?",
                   (dedup_key(esp),)).fetchone()
eq("the title is stored as published", row["title"], "ESP32-S3 gets a new SDK")
eq("the url is stored as published", row["url"], "https://example.com/esp32")
eq("the canonical url is stored too", row["canonical_url"], esp.canonical_url)


# -- re-sighting: what moves and what does not -----------------------------

r2 = mod.start_run(conn, NOW + HOUR)
mod.save(conn, r2, {
    # Same story, a second source, an *earlier* timestamp, seen an hour later.
    "ESP32": [story(item("ESP32-S3 gets a new SDK", "https://example.com/esp32",
                         "lobsters", published_at=NOW - 3 * HOUR),
                    ["ESP32"], sources=("lobsters",), score=0.77)],
}, NOW + HOUR)

row = conn.execute("SELECT * FROM items WHERE dedup_key=?",
                   (dedup_key(esp),)).fetchone()
eq("first_seen_at never moves once set", row["first_seen_at"],
   mod.to_db(NOW))
eq("published_at keeps the earliest of every sighting", row["published_at"],
   mod.to_db(NOW - 3 * HOUR))
eq("a second sighting adds no second items row", counts(conn, "items"), 2)

sources = {r["source_id"] for r in conn.execute(
    "SELECT source_id FROM item_sources WHERE dedup_key=?", (dedup_key(esp),))}
eq("item_sources accumulates the union", sources, {"hn", "lobsters"})

# A sighting with no timestamp must not wipe the one a real source gave us.
r3 = mod.start_run(conn, NOW + 2 * HOUR)
mod.save(conn, r3, {
    "ESP32": [story(item("ESP32-S3 gets a new SDK", "https://example.com/esp32",
                         "genk"), ["ESP32"], score=0.5)],
}, NOW + 2 * HOUR)
row = conn.execute("SELECT published_at FROM items WHERE dedup_key=?",
                   (dedup_key(esp),)).fetchone()
eq("a NULL published_at never overwrites a real one", row["published_at"],
   mod.to_db(NOW - 3 * HOUR))


# -- day_matches: the read-back the page renders ---------------------------

day = mod.day_matches(conn, NOW - HOUR, NOW + 6 * HOUR)

eq("day_matches keys by group label", set(day), {"ESP32", "Rust"})
eq("one row per story per group, not one per sighting", len(day["ESP32"]), 1)

hit = day["ESP32"][0]
eq("the best score across the day's runs wins", hit["score"], 0.91)
eq("the sources are joined into the row", set(hit["sources"]),
   {"hn", "lobsters", "genk"})
eq("published_at comes back as an aware datetime", hit["published_at"],
   NOW - 3 * HOUR)
eq("first_seen_at comes back as an aware datetime", hit["first_seen_at"], NOW)
eq("the title travels with the row", hit["title"], "ESP32-S3 gets a new SDK")

older = mod.day_matches(conn, NOW - 2 * DAY, NOW - DAY)
eq("a window with no run in it is empty, not an error", older, {})

# A run outside the window contributes nothing, even for a story that is also
# inside it - the page shows a day, not everything ever matched.
r_old = mod.start_run(conn, NOW - 3 * DAY)
mod.save(conn, r_old, {"Rust": [story(quiet, ["Rust"], score=9.9)]},
         NOW - 3 * DAY)
eq("a run outside the window cannot raise today's score",
   mod.day_matches(conn, NOW - HOUR, NOW + 6 * HOUR)["Rust"][0]["score"], 0.42)


# -- run_matches: the read-back a notification sends ------------------------

# The page shows a day; a message shows a run. Same row shape, different
# window - and a different score, because a run reports what *it* scored the
# story at rather than the best any run managed today.
this_run = mod.run_matches(conn, r2)

eq("run_matches sees only the groups that run matched", set(this_run), {"ESP32"})
eq("one row per story per group", len(this_run["ESP32"]), 1)
eq("the row carries that run's own score, not the day's best",
   this_run["ESP32"][0]["score"], 0.77)
eq("the row shape is the one the page already renders",
   set(this_run["ESP32"][0]), set(day["ESP32"][0]))
eq("the accumulated sources travel with it",
   set(this_run["ESP32"][0]["sources"]), {"hn", "lobsters", "genk"})
eq("a run id nothing was saved under is empty, not an error",
   mod.run_matches(conn, "20990101T000000Z"), {})


# -- the seen-set ----------------------------------------------------------

keys = [dedup_key(esp), dedup_key(quiet)]
eq("nothing is reported before anything is sent",
   set(mod.unreported(conn, keys, "telegram")), set(keys))

mod.mark_reported(conn, [dedup_key(esp)], "telegram", NOW)
eq("a sent story drops out of the channel's unreported list",
   mod.unreported(conn, keys, "telegram"), [dedup_key(quiet)])
eq("another channel is untouched by it",
   set(mod.unreported(conn, keys, "discord")), set(keys))

mod.mark_reported(conn, [dedup_key(esp)], "telegram", NOW + HOUR)
eq("marking the same story twice writes one row", counts(conn, "reported"), 1)
eq("unreported on an empty key list is empty",
   mod.unreported(conn, [], "telegram"), [])


# -- finish_run ------------------------------------------------------------

mod.finish_run(conn, r1, NOW + HOUR, items_fetched=597, items_matched=209,
               errors=[("r_embedded", "Name or service not known")])
row = conn.execute("SELECT * FROM runs WHERE run_id=?", (r1,)).fetchone()
eq("finish_run records what the cycle fetched", row["items_fetched"], 597)
eq("finish_run records what survived the filter", row["items_matched"], 209)
check("the failing sources are recorded as JSON",
      "r_embedded" in (row["errors"] or ""), row["errors"])
eq("finish_run stamps the end", row["finished_at"], mod.to_db(NOW + HOUR))
conn.close()


# -- retention -------------------------------------------------------------

root = data_dir()
conn = mod.open_db(root)
days = root / "days"
days.mkdir(parents=True, exist_ok=True)
(days / "2026-09-05.html").write_text("today", encoding="utf-8")
(days / "2026-07-01.html").write_text("ancient", encoding="utf-8")

fresh = item("Fresh story", "https://example.com/fresh", "hn")
stale = item("Stale story", "https://example.com/stale", "hn")
r_now = mod.start_run(conn, NOW)
mod.save(conn, r_now, {"ESP32": [story(fresh, ["ESP32"])]}, NOW)
r_then = mod.start_run(conn, NOW - 60 * DAY)
mod.save(conn, r_then, {"ESP32": [story(stale, ["ESP32"])]}, NOW - 60 * DAY)
mod.mark_reported(conn, [dedup_key(stale)], "telegram", NOW - 60 * DAY)

eq("retention_days 0 keeps everything - rows",
   mod.prune(conn, root, 0, NOW), (0, 0))
eq("retention_days 0 keeps everything - items", counts(conn, "items"), 2)
check("retention_days 0 keeps every day file",
      (days / "2026-07-01.html").is_file())

rows, files = mod.prune(conn, root, 30, NOW)
check("prune reports what it deleted", rows > 0 and files == 1,
      "rows={} files={}".format(rows, files))
eq("the story past the window is gone", counts(conn, "items"), 1)
eq("its sources go with it", counts(conn, "item_sources"), 1)
eq("its matches go with it", counts(conn, "matches"), 1)
eq("its seen-set entry goes with it", counts(conn, "reported"), 0)
eq("the run past the window is gone", counts(conn, "runs"), 1)
check("the day file past the window is deleted",
      not (days / "2026-07-01.html").exists())
check("the current day file survives", (days / "2026-09-05.html").is_file())
eq("the story inside the window survives",
   conn.execute("SELECT title FROM items").fetchone()["title"], "Fresh story")
conn.close()


# -- a store written by a newer version is refused, never downgraded --------

root = data_dir()
conn = mod.open_db(root)
conn.execute("PRAGMA user_version = {}".format(mod.SCHEMA_VERSION + 1))
conn.commit()
conn.close()
try:
    mod.open_db(root).close()
    check("a store from a newer schema is refused", False, "open_db returned")
except mod.StoreError:
    check("a store from a newer schema is refused", True)
except sqlite3.Error as exc:
    check("a store from a newer schema is refused", False,
          "raised sqlite3.Error instead: {}".format(exc))


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
