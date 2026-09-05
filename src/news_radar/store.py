"""Persistence: one SQLite file holding every story ever seen, and the seen-set.

Layer 4. It imports the standard library and `item` (a leaf) and nothing else -
in particular no `config`, exactly like layer 3: `data_dir`, `retention_days`
and every timestamp arrive as arguments that `__main__.py` builds. That is why
`tests/test_store.py` runs on a bare Python with neither PyYAML nor feedparser
installed.

Timestamps are stored as ISO-8601 **UTC** strings. Every one of them carries the
same `+00:00` suffix, so `<` and `>` in SQL mean what they say and no comparison
has to go through Python. Local time is a render-time concern and never reaches
this file.

Contract: docs/memory-ai/data/news-item.md (SQLite store)
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3

from pathlib import Path

from .item import dedup_key

__all__ = [
    "StoreError", "SCHEMA_VERSION", "DB_NAME", "open_db", "to_db", "from_db",
    "start_run", "finish_run", "save", "day_matches", "run_matches",
    "unreported", "mark_reported", "backup", "prune",
]

log = logging.getLogger("news_radar.store")

DB_NAME = "news.db"
DAYS_DIR = "days"

# Bumped whenever the shape below changes. `open_db` migrates forward only: a
# file written by a newer version is refused rather than downgraded, because
# the alternative is silently dropping columns the operator's other copy needs.
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE items (
    dedup_key     TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    published_at  TEXT
);

-- One row per (story, source that carried it). A table rather than a JSON
-- column on `items`: the union of sources is then an INSERT OR IGNORE away,
-- instead of a read-modify-write on every re-sighting.
CREATE TABLE item_sources (
    dedup_key TEXT NOT NULL,
    source_id TEXT NOT NULL,
    PRIMARY KEY (dedup_key, source_id)
);

CREATE TABLE matches (
    dedup_key  TEXT NOT NULL,
    group_name TEXT NOT NULL,
    score      REAL NOT NULL,
    run_id     TEXT NOT NULL,
    PRIMARY KEY (dedup_key, group_name, run_id)
);

-- The seen-set. Keyed per channel on purpose: enabling Discord later must not
-- count stories already pushed to Telegram as sent.
CREATE TABLE reported (
    dedup_key   TEXT NOT NULL,
    channel     TEXT NOT NULL,
    reported_at TEXT NOT NULL,
    PRIMARY KEY (dedup_key, channel)
);

CREATE TABLE runs (
    run_id        TEXT PRIMARY KEY,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    items_fetched INTEGER,
    items_matched INTEGER,
    errors        TEXT
);

CREATE INDEX matches_by_run ON matches (run_id);
CREATE INDEX runs_by_start ON runs (started_at);
"""


class StoreError(Exception):
    """The store cannot be used as it stands. Never raised for a missing file."""


def to_db(moment):
    """An aware datetime as the one string spelling this file stores."""
    if moment is None:
        return None
    return moment.astimezone(dt.timezone.utc).isoformat()


def from_db(text):
    """Back to an aware UTC datetime, or None for a NULL column."""
    if not text:
        return None
    return dt.datetime.fromisoformat(text)


def open_db(data_dir):
    """Connect to `<data_dir>/news.db`, creating and migrating it as needed.

    The directory is created too: on a fresh homelab `output/` does not exist
    until the first run, and failing there would cost the whole cycle for a
    `mkdir`.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(data_dir / DB_NAME))
    conn.row_factory = sqlite3.Row
    version = conn.execute("PRAGMA user_version").fetchone()[0]

    if version == SCHEMA_VERSION:
        return conn
    if version > SCHEMA_VERSION:
        conn.close()
        raise StoreError(
            "{} was written by schema version {}, this build understands {} - "
            "refusing to downgrade it".format(
                data_dir / DB_NAME, version, SCHEMA_VERSION))

    if version == 0:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA user_version = {}".format(SCHEMA_VERSION))
        conn.commit()
        log.info("created %s at schema version %d",
                 data_dir / DB_NAME, SCHEMA_VERSION)
    return conn


def start_run(conn, started_at):
    """Open a row in `runs` and return its id. Ids are the UTC start compacted."""
    base = started_at.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = base
    # Two cycles inside one second only happen under a test or a hand-run
    # `--once` pair, but a PK collision there would abort the run for nothing.
    for suffix in range(2, 100):
        try:
            conn.execute("INSERT INTO runs (run_id, started_at) VALUES (?, ?)",
                         (run_id, to_db(started_at)))
            break
        except sqlite3.IntegrityError:
            run_id = "{}-{}".format(base, suffix)
    conn.commit()
    return run_id


def finish_run(conn, run_id, finished_at, items_fetched=0, items_matched=0,
               errors=()):
    """Close the run's row. `errors` is whatever `crawl()` collected, as JSON."""
    conn.execute(
        "UPDATE runs SET finished_at=?, items_fetched=?, items_matched=?, "
        "errors=? WHERE run_id=?",
        (to_db(finished_at), items_fetched, items_matched,
         json.dumps([list(e) for e in errors]), run_id))
    conn.commit()


def save(conn, run_id, ranked, now):
    """{label: [Story]} -> rows. Returns the number of match rows written.

    Re-sighting rules, all of them in the one UPSERT below:

    - `first_seen_at` never moves. It is the answer to "is this new?", which is
      the whole of P4's diff.
    - `published_at` keeps the **earliest** non-null anyone reported. A source
      that gives no timestamp must not erase one that did, so a NULL never wins.
    - the source set accumulates, because `item_sources` ignores a duplicate.
    """
    written = 0
    for label, stories in ranked.items():
        for story in stories:
            item = story.item
            key = dedup_key(item)
            published = to_db(story.published_at or item.published_at)

            conn.execute(
                "INSERT INTO items (dedup_key, title, url, canonical_url,"
                " first_seen_at, published_at) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(dedup_key) DO UPDATE SET published_at ="
                "   CASE WHEN excluded.published_at IS NOT NULL"
                "         AND (items.published_at IS NULL"
                "              OR excluded.published_at < items.published_at)"
                "        THEN excluded.published_at ELSE items.published_at END",
                (key, item.title, item.url, item.canonical_url, to_db(now),
                 published))

            conn.executemany(
                "INSERT OR IGNORE INTO item_sources (dedup_key, source_id)"
                " VALUES (?, ?)",
                [(key, source_id) for source_id in story.source_ids])

            conn.execute(
                "INSERT OR REPLACE INTO matches (dedup_key, group_name, score,"
                " run_id) VALUES (?, ?, ?, ?)",
                (key, label, story.score, run_id))
            written += 1

    conn.commit()
    return written


def _matches(conn, where, params):
    """{label: [row]} for whichever slice of `matches` the caller selects.

    One row per (story, group) whatever the run count, and the **best** score in
    the slice wins: a story that got fresher during the day should not be ranked
    by the run that saw it first. Over a single run that MAX is a no-op, because
    the primary key already allows one row per (story, group, run).

    The row shape is the one contract the page and the senders share - change it
    here and both of them see the change.
    """
    rows = conn.execute(
        "SELECT m.group_name, i.dedup_key, i.title, i.url, i.canonical_url,"
        "       MAX(m.score) AS score, i.published_at, i.first_seen_at,"
        "       (SELECT group_concat(s.source_id) FROM item_sources s"
        "         WHERE s.dedup_key = i.dedup_key) AS sources"
        "  FROM matches m"
        "  JOIN items i ON i.dedup_key = m.dedup_key"
        "  JOIN runs  r ON r.run_id    = m.run_id"
        " WHERE " + where +
        " GROUP BY m.group_name, i.dedup_key"
        " ORDER BY m.group_name, score DESC, i.first_seen_at",
        params).fetchall()

    grouped = {}
    for row in rows:
        grouped.setdefault(row["group_name"], []).append({
            "dedup_key": row["dedup_key"],
            "title": row["title"],
            "url": row["url"],
            "canonical_url": row["canonical_url"],
            "score": row["score"],
            "published_at": from_db(row["published_at"]),
            "first_seen_at": from_db(row["first_seen_at"]),
            "sources": tuple((row["sources"] or "").split(",")) if row["sources"]
                       else (),
        })
    return grouped


def day_matches(conn, start_utc, end_utc):
    """Every story matched by a run inside the window, grouped by label.

    This - not the shortlist still in memory - is what the page renders. A
    restart at noon would otherwise publish an afternoon that has forgotten its
    own morning, and "history survives a restart" is the phase's definition of
    done.
    """
    return _matches(conn, "r.started_at >= ? AND r.started_at < ?",
                    (to_db(start_utc), to_db(end_utc)))


def run_matches(conn, run_id):
    """Just this run's stories, in the row shape `day_matches()` returns.

    What a notification is built from. The page shows a day and a message shows
    a run, but both read the store rather than the shortlist in memory - so the
    story that goes out is the same row, with the same score and the same source
    list, as the one on the page.
    """
    return _matches(conn, "m.run_id = ?", (run_id,))


def unreported(conn, dedup_keys, channel):
    """The keys of `dedup_keys` this channel has not been told about yet.

    Per channel, in the caller's order. P4's whole "nothing is re-sent" rule is
    this function plus `mark_reported`.
    """
    keys = list(dedup_keys)
    if not keys:
        return []
    placeholders = ",".join("?" * len(keys))
    sent = {r["dedup_key"] for r in conn.execute(
        "SELECT dedup_key FROM reported WHERE channel=? AND dedup_key IN ({})"
        .format(placeholders), [channel] + keys)}
    return [k for k in keys if k not in sent]


def mark_reported(conn, dedup_keys, channel, when):
    """Record that these stories went out on this channel. Idempotent.

    Called only **after** the chunk was accepted: a crash between send and write
    re-sends, and a duplicate is the acceptable failure where a silently dropped
    story is not.
    """
    conn.executemany(
        "INSERT OR IGNORE INTO reported (dedup_key, channel, reported_at)"
        " VALUES (?, ?, ?)",
        [(key, channel, to_db(when)) for key in dedup_keys])
    conn.commit()


def backup(conn, backup_dir, now, keep):
    """One dated copy of the store per day. Returns `(path | None, removed)`.

    Taken with SQLite's own online-backup API rather than by copying the file:
    the crawl service holds this connection open and a `-wal` may be mid-flush,
    so a filesystem copy can produce a database that opens and is missing the
    last write. `conn.backup()` is the supported way to snapshot a live one.

    Three decisions worth stating:

    - **The filename is the rotation key.** `news-<UTC date>.db` sorts as the
      date does, so keeping the newest N is a slice and nothing has to parse a
      name back into a time. A second cycle the same day is a no-op - at the
      default interval there are 48 of them, and 48 identical copies is not an
      archive.
    - **UTC, like every other timestamp in this file.** Local time is a
      render-time concern and does not reach layer 4. A backup taken at 06:00
      Ho Chi Minh sits under the previous UTC date, which is correct and
      uninteresting: what matters is that the ordering is total.
    - **`backup_dir` is a caller's argument and must never be under
      `data_dir`.** That directory is served to the public web by Caddy, and a
      backup there is one Caddyfile line away from handing a stranger the whole
      archive in one request. `config.yaml` documents it; this file cannot
      check it, because it does not know what is being served.

    `keep <= 0` is the off switch: nothing is written, nothing is deleted, and
    no directory is created.
    """
    if not keep or keep <= 0:
        return (None, 0)

    backup_dir = Path(backup_dir)
    stamp = now.astimezone(dt.timezone.utc).date().isoformat()
    path = backup_dir / "news-{}.db".format(stamp)
    if path.exists():
        return (None, 0)

    backup_dir.mkdir(parents=True, exist_ok=True)

    # Written under a temporary name and renamed into place: a backup that was
    # interrupted half-way must not be left looking like a good one, which is
    # the failure you would only discover on the day you needed it.
    partial = path.with_name(path.name + ".part")
    try:
        dest = sqlite3.connect(str(partial))
        try:
            conn.backup(dest)
        finally:
            dest.close()
        partial.replace(path)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    existing = sorted(backup_dir.glob("news-*.db"))
    removed = 0
    for old in existing[:-keep]:
        old.unlink()
        removed += 1

    log.info("backup: wrote %s, %d older copy(ies) dropped, %d kept",
             path, removed, min(len(existing), keep))
    return (path, removed)


def prune(conn, data_dir, retention_days, now):
    """Drop rows and `days/` files older than the window. Returns (rows, files).

    `retention_days = 0` means keep everything, and remains the fallback for an
    **absent** key so that upgrading a deployment never starts deleting rows
    nobody chose to lose. The shipped `config.yaml` sets `90`: an unattended
    radar with no ceiling is a disk that fills on a weekend, and P6's definition
    of done says "no disk growth". `backup()` runs immediately before this, so
    the first prune always has a copy standing in front of it.
    """
    if not retention_days or retention_days <= 0:
        return (0, 0)

    cutoff = now - dt.timedelta(days=retention_days)
    cutoff_db = to_db(cutoff)
    doomed = "SELECT dedup_key FROM items WHERE first_seen_at < ?"

    rows = 0
    for statement in (
            "DELETE FROM item_sources WHERE dedup_key IN ({})".format(doomed),
            "DELETE FROM matches WHERE dedup_key IN ({})".format(doomed),
            "DELETE FROM reported WHERE dedup_key IN ({})".format(doomed),
            "DELETE FROM items WHERE first_seen_at < ?"):
        rows += conn.execute(statement, (cutoff_db,)).rowcount
    rows += conn.execute("DELETE FROM runs WHERE started_at < ?",
                         (cutoff_db,)).rowcount
    conn.commit()

    # Day snapshots are named `YYYY-MM-DD.html` in local time, so the string
    # sorts as the date does and no filename has to be parsed back into one.
    files = 0
    cutoff_day = cutoff.date().isoformat()
    for path in sorted(Path(data_dir).joinpath(DAYS_DIR).glob("*.html")):
        if path.stem < cutoff_day:
            path.unlink()
            files += 1

    if rows or files:
        log.info("retention: %d row(s) and %d day file(s) older than %s dropped",
                 rows, files, cutoff_day)
    return (rows, files)
