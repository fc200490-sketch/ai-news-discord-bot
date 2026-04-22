"""Extract thumbnail URL for a feed entry, with og:image fallback."""
import logging

import aiohttp
from bs4 import BeautifulSoup

from config import ENABLE_THUMBNAILS

logger = logging.getLogger(__name__)

_OG_TIMEOUT = aiohttp.ClientTimeout(total=5)


def from_entry(entry) -> str | None:
    thumbs = entry.get("media_thumbnail") or []
    for t in thumbs:
        url = t.get("url")
        if url:
            return url

    media = entry.get("media_content") or []
    for m in media:
        url = m.get("url")
        mtype = (m.get("type") or "").lower()
        if url and (not mtype or mtype.startswith("image")):
            return url

    for enc in entry.get("enclosures") or []:
        url = enc.get("href") or enc.get("url")
        mtype = (enc.get("type") or "").lower()
        if url and mtype.startswith("image"):
            return url

    return None


async def from_og(session: aiohttp.ClientSession, page_url: str, cache: dict) -> str | None:
    if not ENABLE_THUMBNAILS:
        return None
    if page_url in cache:
        return cache[page_url]
    try:
        async with session.get(page_url, timeout=_OG_TIMEOUT, allow_redirects=True) as resp:
            if resp.status != 200:
                cache[page_url] = None
                return None
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype.lower():
                cache[page_url] = None
                return None
            html = await resp.text(errors="ignore")
    except Exception as e:
        logger.debug("og:image fetch fallito per %s: %s", page_url, e)
        cache[page_url] = None
        return None

    try:
        soup = BeautifulSoup(html, "html.parser")
        for prop in ("og:image", "twitter:image"):
            tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
            if tag and tag.get("content"):
                cache[page_url] = tag["content"].strip()
                return cache[page_url]
    except Exception as e:
        logger.debug("parse og:image fallito per %s: %s", page_url, e)

    cache[page_url] = None
    return None


async def resolve(session: aiohttp.ClientSession, entry, page_url: str, cache: dict) -> str | None:
    url = from_entry(entry)
    if url:
        return url
    if not ENABLE_THUMBNAILS or not page_url:
        return None
    return await from_og(session, page_url, cache)
