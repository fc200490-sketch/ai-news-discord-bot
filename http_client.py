"""Shared HTTP GET with retry + timeout, used by feed fetcher and scrapers."""
import asyncio
import logging

import aiohttp

from config import ENABLE_FEED_RETRY

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=20)
RETRY_BACKOFFS = (0.5, 2.0)


async def http_get(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict | None = None,
    timeout: aiohttp.ClientTimeout | None = None,
) -> tuple[int, dict, bytes]:
    """GET with retry on 5xx / transient errors. Returns (status, headers, body).
    Body is empty on non-200 responses."""
    attempts = (0, *(RETRY_BACKOFFS if ENABLE_FEED_RETRY else ()))
    last_exc: BaseException | None = None
    headers = headers or {}
    timeout = timeout or DEFAULT_TIMEOUT
    for idx, delay in enumerate(attempts):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with session.get(url, timeout=timeout, headers=headers) as resp:
                if resp.status in (500, 502, 503, 504) and idx < len(attempts) - 1:
                    last_exc = RuntimeError(f"HTTP {resp.status}")
                    continue
                body = await resp.read() if resp.status == 200 else b""
                return resp.status, dict(resp.headers), body
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_exc = e
            if idx == len(attempts) - 1:
                raise
    if last_exc:
        raise last_exc
    raise RuntimeError("unreachable")
