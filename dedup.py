"""Semantic dedup: embedding cosine similarity, with SequenceMatcher fallback."""
import logging
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import embeddings
import storage

logger = logging.getLogger(__name__)

_STOPWORDS = {
    # IT
    "il", "la", "lo", "i", "gli", "le", "un", "una", "uno",
    "di", "da", "in", "su", "con", "per", "tra", "fra",
    "e", "o", "ma", "che", "non", "del", "della", "dei", "delle", "degli",
    "al", "alla", "agli", "alle", "nel", "nella", "nei", "negli", "nelle",
    "è", "sono", "ha", "hanno", "sia",
    # EN
    "the", "a", "an", "of", "to", "on", "for", "and", "or", "but",
    "is", "are", "was", "were", "be", "been", "being", "with", "as", "at",
    "by", "from", "this", "that", "these", "those", "it", "its",
    "new", "says", "said", "will", "has", "have", "had", "can",
}

_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    if not title:
        return ""
    t = title.lower()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    tokens = [w for w in t.split() if w and w not in _STOPWORDS and len(w) > 1]
    return " ".join(tokens)


def lexical_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def find_semantic_duplicate(
    item: dict,
    candidates: list[dict],
    embed_threshold: float,
    lexical_threshold: float,
    window_hours: int,
) -> dict | None:
    """Return the candidate that duplicates `item`, or None.

    `item` must have: title, title_norm. Optional: embedding.
    Candidates: list of dicts with url, ts (iso), title_norm, embedding.
    Uses embedding cosine when both sides have it, else falls back to lexical.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    item_emb = item.get("embedding")
    item_norm = item.get("title_norm") or normalize_title(item.get("title", ""))
    for cand in candidates:
        ts_raw = cand.get("ts")
        try:
            ts = datetime.fromisoformat(ts_raw) if ts_raw else None
        except (TypeError, ValueError):
            ts = None
        if ts is None or ts < cutoff:
            continue

        cand_emb = cand.get("embedding")
        if item_emb and cand_emb:
            score = embeddings.cosine(item_emb, cand_emb)
            if score >= embed_threshold:
                return cand
            continue

        cand_norm = cand.get("title_norm") or ""
        if not item_norm or not cand_norm:
            continue
        if lexical_similarity(item_norm, cand_norm) >= lexical_threshold:
            return cand
    return None


def load_seen_recent(window_hours: int) -> list[dict]:
    return storage.load_recent_posted(window_hours)


def get_posted_urls() -> set[str]:
    return storage.get_posted_urls()


def mark_seen(items: list[dict]) -> None:
    storage.prune()
    enriched = []
    for item in items:
        enriched.append({
            "url": item.get("url"),
            "title_norm": item.get("title_norm") or normalize_title(item.get("title", "")),
            "embedding": item.get("embedding"),
            "source": item.get("source", ""),
        })
    storage.mark_posted(enriched)
