"""Fetch and normalize RSS entries."""
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import aiohttp
import feedparser

from config import LOOKBACK_HOURS
from feeds import AI_KEYWORDS, all_feeds

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = aiohttp.ClientTimeout(total=20)
USER_AGENT = "AINewsDiscordBot/1.0 (+https://github.com/)"


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
    ]).lower()
    return any(k in blob for k in AI_KEYWORDS)


async def _fetch_one(session: aiohttp.ClientSession, source: str, url: str, ai_dedicated: bool, language: str):
    try:
        async with session.get(url, timeout=HTTP_TIMEOUT) as resp:
            resp.raise_for_status()
            raw = await resp.read()
    except Exception as e:
        logger.warning("Fetch fallito per %s (%s): %s", source, url, e)
        return []

    parsed = feedparser.parse(raw)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    items = []
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
        items.append({
            "title": title.strip(),
            "url": link.strip(),
            "summary": _strip_html(entry.get("summary", ""))[:500],
            "source": source,
            "published": pub,
            "language": language,
        })
    logger.info("Feed %s: %d entry nelle ultime %dh", source, len(items), LOOKBACK_HOURS)
    return items


async def fetch_all() -> list[dict]:
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [
            _fetch_one(session, name, url, ai_dedicated, lang)
            for name, url, ai_dedicated, lang in all_feeds()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)
    flat = [item for batch in results for item in batch]
    flat.sort(key=lambda x: x["published"], reverse=True)
    return flat
