"""Extract thumbnail URL for a feed entry, with og:image fallback."""
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from config import ENABLE_THUMBNAILS

logger = logging.getLogger(__name__)

_OG_TIMEOUT = aiohttp.ClientTimeout(total=5)


def _is_safe_http_url(url: str) -> bool:
    """Reject non-http(s) schemes and hosts that resolve to private/loopback/
    link-local IPs (basic SSRF guard). Best-effort: DNS can be rebound."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


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
    cache_key = page_url
    if cache_key in cache:
        return cache[cache_key]
    if not _is_safe_http_url(page_url):
        cache[cache_key] = None
        return None
    try:
        # allow_redirects=False so a public URL can't redirect into a private
        # network and bypass the SSRF guard. If a redirect is needed, we resolve
        # the Location ourselves after re-validating it.
        async with session.get(page_url, timeout=_OG_TIMEOUT, allow_redirects=False) as resp:
            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location")
                if not loc:
                    cache[cache_key] = None
                    return None
                next_url = urljoin(page_url, loc)
                if not _is_safe_http_url(next_url) or next_url == page_url:
                    cache[cache_key] = None
                    return None
                async with session.get(next_url, timeout=_OG_TIMEOUT, allow_redirects=False) as r2:
                    if r2.status != 200:
                        cache[cache_key] = None
                        return None
                    ctype = r2.headers.get("Content-Type", "")
                    if "html" not in ctype.lower():
                        cache[cache_key] = None
                        return None
                    html = await r2.text(errors="ignore")
                    page_url = next_url  # resolve relative og:image against final URL
            elif resp.status != 200:
                cache[cache_key] = None
                return None
            else:
                ctype = resp.headers.get("Content-Type", "")
                if "html" not in ctype.lower():
                    cache[cache_key] = None
                    return None
                html = await resp.text(errors="ignore")
    except Exception as e:
        logger.debug("og:image fetch fallito per %s: %s", page_url, e)
        cache[cache_key] = None
        return None

    try:
        soup = BeautifulSoup(html, "html.parser")
        for prop in ("og:image", "twitter:image"):
            tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
            if tag and tag.get("content"):
                raw = tag["content"].strip()
                # Resolve relative URLs against the (possibly redirected) page URL.
                resolved = urljoin(page_url, raw)
                if urlparse(resolved).scheme not in ("http", "https"):
                    cache[cache_key] = None
                    return None
                cache[cache_key] = resolved
                return resolved
    except Exception as e:
        logger.debug("parse og:image fallito per %s: %s", page_url, e)

    cache[cache_key] = None
    return None


async def resolve(session: aiohttp.ClientSession, entry, page_url: str, cache: dict) -> str | None:
    url = from_entry(entry)
    if url:
        return url
    if not ENABLE_THUMBNAILS or not page_url:
        return None
    return await from_og(session, page_url, cache)
