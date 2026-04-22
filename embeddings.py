"""Gemini embeddings for semantic dedup, with graceful fallback."""
import asyncio
import logging
import math

from config import ENABLE_EMBEDDING_DEDUP, GEMINI_API_KEY, GEMINI_EMBED_MODEL

logger = logging.getLogger(__name__)

_client = None
_client_failed = False


def _get_client():
    global _client, _client_failed
    if _client is not None or _client_failed:
        return _client
    if not GEMINI_API_KEY:
        _client_failed = True
        return None
    try:
        from google import genai
        _client = genai.Client(api_key=GEMINI_API_KEY)
        return _client
    except Exception as e:
        logger.warning("Embedding client non inizializzato: %s", e)
        _client_failed = True
        return None


async def embed(text: str) -> list[float] | None:
    if not ENABLE_EMBEDDING_DEDUP or not text:
        return None
    client = _get_client()
    if client is None:
        return None
    try:
        resp = await asyncio.to_thread(
            client.models.embed_content,
            model=GEMINI_EMBED_MODEL,
            contents=text,
        )
        values = _extract_values(resp)
        return values
    except Exception as e:
        logger.warning("Embedding fallito: %s", e)
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
