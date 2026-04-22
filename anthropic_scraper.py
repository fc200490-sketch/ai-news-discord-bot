"""HTML scraper for anthropic.com/news (no RSS feed available upstream).

Extracts news entries (title, url, date, optional excerpt) and returns them
in the same dict format as RSS items consumed by news_fetcher.
"""
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

from http_client import http_get

logger = logging.getLogger(__name__)

SOURCE_NAME = "Anthropic"
NEWS_URL = "https://www.anthropic.com/news"
_TIMEOUT = aiohttp.ClientTimeout(total=15)
_DATE_RE = re.compile(r"^[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}$")


def _parse_date(text: str) -> datetime | None:
    text = (text or "").strip()
    if not _DATE_RE.match(text):
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _title_from_anchor(a) -> str | None:
    """Featured cards use h2/h3; list items use span with class containing 'title'."""
    h = a.find(["h2", "h3", "h4"])
    if h:
        text = h.get_text(" ", strip=True)
        if text:
            return text
    span = a.find("span", class_=lambda c: bool(c) and "title" in c.lower())
    if span:
        text = span.get_text(" ", strip=True)
        if text:
            return text
    return None


def _date_for_anchor(a):
    t = a.find("time")
    if t:
        d = _parse_date(t.get_text(strip=True))
        if d:
            return d
    parent = a.parent
    for _ in range(3):
        if parent is None:
            break
        t = parent.find("time")
        if t:
            d = _parse_date(t.get_text(strip=True))
            if d:
                return d
        parent = parent.parent
    return None


def _extract(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    items: list[dict] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("/news/") or href in ("/news/", "/news"):
            continue
        if href in seen:
            continue
        title = _title_from_anchor(a)
        if not title or len(title) < 5:
            continue
        published = _date_for_anchor(a)
        if published is None:
            continue
        excerpt_tag = a.find("p")
        excerpt = excerpt_tag.get_text(" ", strip=True) if excerpt_tag else ""
        seen.add(href)
        items.append({
            "title": title,
            "url": urljoin("https://www.anthropic.com", href),
            "summary": excerpt[:500],
            "source": SOURCE_NAME,
            "published": published,
            "language": "en",
            "thumbnail_url": None,
        })
    return items


async def fetch(session: aiohttp.ClientSession, lookback_hours: int) -> list[dict]:
    try:
        status, _headers, raw = await http_get(session, NEWS_URL, timeout=_TIMEOUT)
    except Exception as e:
        logger.warning("Anthropic scraper fetch fallito: %s", e)
        return []
    if status != 200:
        logger.warning("Anthropic scraper: HTTP %s", status)
        return []
    try:
        html = raw.decode("utf-8", errors="ignore")
    except Exception as e:
        logger.warning("Anthropic scraper decode fallito: %s", e)
        return []

    items = _extract(html)
    if not items:
        # Raise to ERROR so Fly logs surface it — markup likely changed.
        logger.error("Anthropic scraper: 0 entry estratte (markup cambiato?)")
        return []

    cutoff = datetime.now(timezone.utc).timestamp() - lookback_hours * 3600
    fresh = [it for it in items if it["published"].timestamp() >= cutoff]
    logger.info(
        "Feed %s (scraper): %d entry totali, %d nelle ultime %dh",
        SOURCE_NAME, len(items), len(fresh), lookback_hours,
    )
    return fresh
