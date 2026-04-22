"""Gemini embeddings for semantic dedup, with rate limiting and graceful fallback."""
import asyncio
import logging
import math
import time

from config import (
    EMBEDDING_CONCURRENCY,
    EMBEDDING_MIN_INTERVAL_SECONDS,
    ENABLE_EMBEDDING_DEDUP,
    GEMINI_EMBED_MODEL,
)
from gemini_client import get_client

logger = logging.getLogger(__name__)

_semaphore: asyncio.Semaphore | None = None
_rate_lock: asyncio.Lock | None = None
_last_call_ts: float = 0.0


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(max(1, EMBEDDING_CONCURRENCY))
    return _semaphore


async def _rate_gate() -> None:
    global _rate_lock, _last_call_ts
    if EMBEDDING_MIN_INTERVAL_SECONDS <= 0:
        return
    if _rate_lock is None:
        _rate_lock = asyncio.Lock()
    async with _rate_lock:
        elapsed = time.monotonic() - _last_call_ts
        wait = EMBEDDING_MIN_INTERVAL_SECONDS - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_ts = time.monotonic()


async def embed(text: str) -> list[float] | None:
    if not ENABLE_EMBEDDING_DEDUP or not text:
        return None
    client = get_client()
    if client is None:
        return None
    sem = _get_semaphore()
    async with sem:
        for attempt in (1, 2):
            await _rate_gate()
            try:
                resp = await asyncio.to_thread(
                    client.models.embed_content,
                    model=GEMINI_EMBED_MODEL,
                    contents=text,
                )
                return _extract_values(resp)
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                    backoff = 45
                    logger.warning("Embedding rate-limit (tentativo %d): %s", attempt, e)
                else:
                    backoff = 2
                    logger.warning("Embedding fallito (tentativo %d): %s", attempt, e)
                if attempt == 1:
                    await asyncio.sleep(backoff)
        return None


def _extract_values(resp) -> list[float] | None:
    embs = getattr(resp, "embeddings", None)
    if embs:
        first = embs[0]
        values = getattr(first, "values", None) or getattr(first, "value", None)
        if values:
            return list(values)
    single = getattr(resp, "embedding", None)
    if single:
        values = getattr(single, "values", None) or getattr(single, "value", None)
        if values:
            return list(values)
        if isinstance(single, list):
            return list(single)
    return None


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))
