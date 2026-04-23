"""Gemini embeddings for semantic dedup, with rate limiting and graceful fallback."""
import asyncio
import logging
import time

import numpy as np

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
    for attempt in (1, 2):
        async with sem:
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
                    logger.warning("Embedding rate-limit (attempt %d): %s", attempt, e)
                else:
                    backoff = 2
                    logger.warning("Embedding failed (attempt %d): %s", attempt, e)
        # Sleep OUTSIDE the semaphore so other coroutines can proceed.
        if attempt == 1:
            await asyncio.sleep(backoff)
    return None


def _extract_values(resp) -> list[float] | None:
    embs = getattr(resp, "embeddings", None)
    if embs:
        values = getattr(embs[0], "values", None)
        if values:
            return list(values)
    return None


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))
