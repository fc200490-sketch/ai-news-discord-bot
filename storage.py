"""SQLite-backed persistent state.

Tables:
  posted         — URL history with ts, title_norm, embedding (JSON), source.
  muted_sources  — per-channel source mutes.
  source_stats   — aggregate up/down counters from reaction feedback.
  feedback       — message_id → url,source mapping for reaction handling.
"""
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from config import FEEDBACK_TTL_DAYS, LEGACY_STATE_FILE, STATE_DB_PATH, STATE_TTL_DAYS

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posted (
    url TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    title_norm TEXT,
    embedding TEXT,
    source TEXT
);
CREATE INDEX IF NOT EXISTS idx_posted_ts ON posted(ts);

CREATE TABLE IF NOT EXISTS muted_sources (
    channel_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (channel_id, source)
);

CREATE TABLE IF NOT EXISTS source_stats (
    source TEXT PRIMARY KEY,
    up INTEGER NOT NULL DEFAULT 0,
    down INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS feedback (
    message_id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    ts TEXT NOT NULL
);
"""

_initialized = False


@contextmanager
def _conn():
    con = sqlite3.connect(STATE_DB_PATH)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    global _initialized
    if _initialized:
        return
    parent = os.path.dirname(os.path.abspath(STATE_DB_PATH))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with _conn() as con:
        con.executescript(_SCHEMA)
    _migrate_from_json()
    _initialized = True
    logger.info("Storage inizializzato: %s", STATE_DB_PATH)


def _migrate_from_json() -> None:
    if not os.path.exists(LEGACY_STATE_FILE):
        return
    try:
        with open(LEGACY_STATE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    migrated = 0
    with _conn() as con:
        cur = con.cursor()
        for url, value in raw.items():
            if isinstance(value, str):
                ts, title_norm = value, ""
            elif isinstance(value, dict):
                ts, title_norm = value.get("ts", ""), value.get("title_norm", "")
            else:
                continue
            if not ts:
                continue
            cur.execute(
                "INSERT OR IGNORE INTO posted(url, ts, title_norm) VALUES (?, ?, ?)",
                (url, ts, title_norm),
            )
            migrated += cur.rowcount
    if migrated:
        logger.info("Migrate: %d entry importate da %s", migrated, LEGACY_STATE_FILE)
    try:
        os.rename(LEGACY_STATE_FILE, LEGACY_STATE_FILE + ".migrated")
    except OSError:
        pass


def prune() -> None:
    now = datetime.now(timezone.utc)
    posted_cutoff = (now - timedelta(days=STATE_TTL_DAYS)).isoformat()
    feedback_cutoff = (now - timedelta(days=FEEDBACK_TTL_DAYS)).isoformat()
    with _conn() as con:
        con.execute("DELETE FROM posted WHERE ts < ?", (posted_cutoff,))
        con.execute("DELETE FROM feedback WHERE ts < ?", (feedback_cutoff,))


def get_posted_urls() -> set[str]:
    with _conn() as con:
        rows = con.execute("SELECT url FROM posted").fetchall()
    return {r[0] for r in rows}


def load_recent_posted(window_hours: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    with _conn() as con:
        rows = con.execute(
            "SELECT url, ts, title_norm, embedding, source FROM posted WHERE ts >= ?",
            (cutoff,),
        ).fetchall()
    items = []
    for url, ts, title_norm, embedding, source in rows:
        emb = None
        if embedding:
            try:
                emb = json.loads(embedding)
            except json.JSONDecodeError:
                emb = None
        items.append({
            "url": url,
            "ts": ts,
            "title_norm": title_norm or "",
            "embedding": emb,
            "source": source or "",
        })
    return items


def mark_posted(items: list[dict]) -> None:
    if not items:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        for item in items:
            url = item.get("url")
            if not url:
                continue
            emb = item.get("embedding")
            emb_json = json.dumps(emb) if emb else None
            con.execute(
                "INSERT OR REPLACE INTO posted(url, ts, title_norm, embedding, source) "
                "VALUES (?, ?, ?, ?, ?)",
                (url, now_iso, item.get("title_norm", ""), emb_json, item.get("source", "")),
            )


def add_muted_source(channel_id: int, source: str) -> None:
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO muted_sources(channel_id, source) VALUES (?, ?)",
            (channel_id, source),
        )


def remove_muted_source(channel_id: int, source: str) -> bool:
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM muted_sources WHERE channel_id = ? AND source = ?",
            (channel_id, source),
        )
        return cur.rowcount > 0


def list_muted_sources(channel_id: int) -> list[str]:
    with _conn() as con:
        rows = con.execute(
            "SELECT source FROM muted_sources WHERE channel_id = ? ORDER BY source",
            (channel_id,),
        ).fetchall()
    return [r[0] for r in rows]


def register_message(message_id: int, url: str, source: str) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO feedback(message_id, url, source, ts) VALUES (?, ?, ?, ?)",
            (message_id, url, source, now_iso),
        )


def get_message_source(message_id: int) -> str | None:
    with _conn() as con:
        row = con.execute(
            "SELECT source FROM feedback WHERE message_id = ?", (message_id,)
        ).fetchone()
    return row[0] if row else None


def bump_source_stat(source: str, delta_up: int, delta_down: int) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO source_stats(source, up, down) VALUES (?, ?, ?) "
            "ON CONFLICT(source) DO UPDATE SET "
            "up = MAX(0, up + ?), down = MAX(0, down + ?)",
            (source, max(0, delta_up), max(0, delta_down), delta_up, delta_down),
        )


def get_source_stats() -> dict[str, dict[str, int]]:
    with _conn() as con:
        rows = con.execute("SELECT source, up, down FROM source_stats").fetchall()
    return {r[0]: {"up": r[1], "down": r[2]} for r in rows}
