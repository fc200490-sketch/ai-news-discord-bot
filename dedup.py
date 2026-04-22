"""Persistent URL dedup state."""
import json
import os
from datetime import datetime, timedelta, timezone

from config import STATE_FILE, STATE_TTL_DAYS


def load_seen() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_seen(data: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def prune(data: dict) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=STATE_TTL_DAYS)
    kept = {}
    for url, ts in data.items():
        try:
            if datetime.fromisoformat(ts) >= cutoff:
                kept[url] = ts
        except ValueError:
            continue
    return kept


def mark_seen(urls: list[str]) -> None:
    data = prune(load_seen())
    now_iso = datetime.now(timezone.utc).isoformat()
    for url in urls:
        data[url] = now_iso
    save_seen(data)
