"""Gemini-assisted editorial gate for AI-news digest quality."""
import asyncio
import json
import logging
import re
import time
from json import JSONDecodeError

from config import (
    AI_CURATION_CONCURRENCY,
    AI_CURATION_MIN_INTERVAL_SECONDS,
    GEMINI_MODEL,
    SUMMARY_LANGUAGE,
)
from gemini_client import get_client

logger = logging.getLogger(__name__)

_MAX_TEXT_CHARS = 1500
_MAX_SUMMARY_CHARS = 320
_MAX_REASON_CHARS = 180
_HTML_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

_LANGUAGE_NAMES = {
    "it": "italiano",
    "en": "English",
    "es": "espanol",
    "fr": "francais",
    "de": "Deutsch",
    "pt": "portugues",
}

_semaphore: asyncio.Semaphore | None = None
_rate_lock: asyncio.Lock | None = None
_last_call_ts: float = 0.0


def _language_label() -> str:
    return _LANGUAGE_NAMES.get(SUMMARY_LANGUAGE, SUMMARY_LANGUAGE)


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(max(1, AI_CURATION_CONCURRENCY))
    return _semaphore


async def _rate_gate() -> None:
    global _rate_lock, _last_call_ts
    if AI_CURATION_MIN_INTERVAL_SECONDS <= 0:
        return
    if _rate_lock is None:
        _rate_lock = asyncio.Lock()
    async with _rate_lock:
        elapsed = time.monotonic() - _last_call_ts
        wait = AI_CURATION_MIN_INTERVAL_SECONDS - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_ts = time.monotonic()


def _truncate(text: str, limit: int) -> str:
    text = _WS_RE.sub(" ", (text or "").strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _sanitize(text: str) -> str:
    text = _HTML_RE.sub(" ", text or "")
    return _truncate(text, _MAX_TEXT_CHARS)


def _extract_json_object(raw: str) -> dict | None:
    decoder = json.JSONDecoder()
    text = raw or ""
    for idx, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[idx:])
        except JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _parse_curation_response(raw: str) -> dict | None:
    obj = _extract_json_object(raw)
    if obj is None:
        return None

    try:
        score = int(float(obj.get("score", 0)))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))

    keep_raw = obj.get("keep")
    if isinstance(keep_raw, bool):
        keep = keep_raw
    elif isinstance(keep_raw, str):
        keep = keep_raw.strip().lower() in ("1", "true", "yes", "y", "si", "sì")
    else:
        keep = score >= 70

    return {
        "keep": keep,
        "score": score,
        "reason": _truncate(str(obj.get("reason") or ""), _MAX_REASON_CHARS),
        "summary": _truncate(str(obj.get("summary") or ""), _MAX_SUMMARY_CHARS),
    }


def _system_prompt() -> str:
    lang = _language_label()
    return (
        "Sei un editor di un digest Discord sulle notizie importanti di AI. "
        "Valuta se una notizia merita di essere pubblicata in un digest curato: "
        "favorisci novita' sostanziali su modelli, agenti, prodotti AI, ricerca, "
        "policy, business AI, fonti ufficiali e sviluppi con impatto reale. "
        "Scarta rumore generico, SEO, opinioni leggere, guide evergreen e notizie tech "
        "non davvero centrate sull'AI.\n\n"
        f"Rispondi solo con JSON valido in {lang}, senza markdown:\n"
        '{"keep": true, "score": 0, "reason": "...", "summary": "..."}\n'
        "score va da 0 a 100. reason deve spiegare in una frase perche' conta. "
        "summary deve essere un TL;DR neutro di 2-3 righe."
    )


def _user_prompt(item: dict) -> str:
    return (
        f"Fonte: {_sanitize(item.get('source', ''))}\n"
        f"Lingua: {_sanitize(item.get('language', ''))}\n"
        f"Titolo: {_sanitize(item.get('title', ''))}\n"
        f"Estratto: {_sanitize(item.get('summary', ''))}\n"
        f"URL: {_sanitize(item.get('url', ''))}"
    )


async def curate(item: dict) -> dict | None:
    client = get_client()
    if client is None:
        return None

    sem = _get_semaphore()
    for attempt in (1, 2):
        async with sem:
            await _rate_gate()
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=GEMINI_MODEL,
                    contents=[_system_prompt(), _user_prompt(item)],
                )
                parsed = _parse_curation_response(getattr(response, "text", "") or "")
                if parsed is not None:
                    logger.info(
                        "Curated score=%d keep=%s title=%r",
                        parsed["score"], parsed["keep"], item.get("title", ""),
                    )
                    return parsed
                logger.warning("Gemini curation empty/invalid output (attempt %d)", attempt)
                backoff = 2
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                    backoff = 45
                    logger.warning("Gemini curation rate-limit (attempt %d): %s", attempt, e)
                else:
                    backoff = 2
                    logger.warning("Gemini curation failed (attempt %d): %s", attempt, e)
        if attempt == 1:
            await asyncio.sleep(backoff)
    return None
