"""Fetch and normalize RSS entries, with ETag caching and retry."""
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import aiohttp
import feedparser

import anthropic_scraper
import image_extractor
from config import ENABLE_FEED_RETRY, FEED_CACHE_FILE, LOOKBACK_HOURS
from feeds import AI_ACRONYM_RE, AI_KEYWORDS_RE, all_feeds

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = aiohttp.ClientTimeout(total=20)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_RETRY_BACKOFFS = (0.5, 2.0)


def _load_feed_cache() -> dict:
    if not os.path.exists(FEED_CACHE_FILE):
        return {}
    try:
        with open(FEED_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_feed_cache(cache: dict) -> None:
    try:
        with open(FEED_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.debug("Impossibile salvare feed cache: %s", e)


def _parse_date(entry) -> datetime | None:
    for field in ("published", "updated", "created"):
        raw = entry.get(field)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None
    return None


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _matches_ai(entry) -> bool:
    blob = " ".join([
        entry.get("title", ""),
        entry.get("summary", ""),
        " ".join(t.get("term", "") for t in entry.get("tags", []) or []),
    ])
    if AI_KEYWORDS_RE.search(blob):
        return True
    # "AI"/"A.I." acronym: case-sensitive to avoid italian preposition "ai".
    return bool(AI_ACRONYM_RE.search(blob))


async def _http_get(session: aiohttp.ClientSession, url: str, headers: dict):
    attempts = (0, *(_RETRY_BACKOFFS if ENABLE_FEED_RETRY else ()))
    last_exc = None
    for idx, delay in enumerate(attempts):
        if delay:
            await asyncio.sleep(delay)
        try:
            resp = await session.get(url, timeout=HTTP_TIMEOUT, headers=headers)
            if resp.status in (500, 502, 503, 504) and idx < len(attempts) - 1:
                resp.release()
                last_exc = RuntimeError(f"HTTP {resp.status}")
                continue
            return resp
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_exc = e
            if idx == len(attempts) - 1:
                raise
    if last_exc:
        raise last_exc


async def _fetch_one(
    session: aiohttp.ClientSession,
    source: str,
    url: str,
    ai_dedicated: bool,
    language: str,
    feed_cache: dict,
    thumb_cache: dict,
):
    headers: dict[str, str] = {}
    cached = feed_cache.get(url) or {}
    if ENABLE_FEED_RETRY:
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]

    try:
        resp = await _http_get(session, url, headers)
    except Exception as e:
        logger.warning("Fetch fallito per %s (%s): %s", source, url, e)
        return []

    try:
        if resp.status == 304:
            logger.info("Feed %s: 304 Not Modified", source)
            return []
        if resp.status != 200:
            logger.warning("Feed %s: HTTP %s", source, resp.status)
            return []
        raw = await resp.read()
        new_etag = resp.headers.get("ETag")
        new_lm = resp.headers.get("Last-Modified")
        if new_etag or new_lm:
            feed_cache[url] = {"etag": new_etag, "last_modified": new_lm}
    finally:
        resp.release()

    parsed = feedparser.parse(raw)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    thumb_tasks = []
    staged = []
    for entry in parsed.entries:
        pub = _parse_date(entry)
        if pub is None or pub < cutoff:
            continue
        if not ai_dedicated and not _matches_ai(entry):
            continue
        link = entry.get("link")
        title = entry.get("title")
        if not link or not title:
            continue
        item = {
            "title": title.strip(),
            "url": link.strip(),
            "summary": _strip_html(entry.get("summary", ""))[:500],
            "source": source,
            "published": pub,
            "language": language,
            "thumbnail_url": None,
        }
        staged.append(item)
        thumb_tasks.append(image_extractor.resolve(session, entry, item["url"], thumb_cache))

    if thumb_tasks:
        thumbs = await asyncio.gather(*thumb_tasks, return_exceptions=True)
        for item, thumb in zip(staged, thumbs):
            if isinstance(thumb, Exception):
                continue
            item["thumbnail_url"] = thumb

    logger.info("Feed %s: %d entry nelle ultime %dh", source, len(staged), LOOKBACK_HOURS)
    return staged


async def fetch_all() -> list[dict]:
    headers = {"User-Agent": USER_AGENT}
    feed_cache = _load_feed_cache() if ENABLE_FEED_RETRY else {}
    thumb_cache: dict = {}
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [
            _fetch_one(session, name, url, ai_dedicated, lang, feed_cache, thumb_cache)
            for name, url, ai_dedicated, lang in all_feeds()
        ]
        tasks.append(anthropic_scraper.fetch(session, LOOKBACK_HOURS))
        results = await asyncio.gather(*tasks, return_exceptions=False)
    if ENABLE_FEED_RETRY:
        _save_feed_cache(feed_cache)
    flat = [item for batch in results for item in batch]
    flat.sort(key=lambda x: x["published"], reverse=True)
    return flat
