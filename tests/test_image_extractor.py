"""Unit tests for SSRF guard + og:image extraction primitives."""
import asyncio
import os
import sys

os.environ.setdefault("DISCORD_TOKEN", "x")
os.environ.setdefault("DISCORD_CHANNEL_ID", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import image_extractor  # noqa: E402


def test_http_scheme_ok():
    assert image_extractor._http_scheme_ok("https://a.com/x.jpg")
    assert image_extractor._http_scheme_ok("http://a.com/x.jpg")
    assert not image_extractor._http_scheme_ok("ftp://a.com/x.jpg")
    assert not image_extractor._http_scheme_ok("javascript:alert(1)")
    assert not image_extractor._http_scheme_ok(None)
    assert not image_extractor._http_scheme_ok("")


def test_scheme_and_host():
    assert image_extractor._scheme_and_host("https://example.com/x") == ("https", "example.com")
    assert image_extractor._scheme_and_host("ftp://example.com") is None
    assert image_extractor._scheme_and_host("https://") is None


def test_ssrf_guard_rejects_private_ip():
    # 10.0.0.1 resolved to itself via getaddrinfo is_private → reject.
    async def _run():
        return await image_extractor._is_safe_http_url("http://10.0.0.1/x")
    assert asyncio.run(_run()) is False


def test_ssrf_guard_rejects_loopback():
    async def _run():
        return await image_extractor._is_safe_http_url("http://127.0.0.1/x")
    assert asyncio.run(_run()) is False


def test_from_entry_prefers_media_thumbnail():
    entry = {
        "media_thumbnail": [{"url": "https://a.com/thumb.jpg"}],
        "media_content": [{"url": "https://a.com/media.jpg", "type": "image/jpeg"}],
    }
    assert image_extractor.from_entry(entry) == "https://a.com/thumb.jpg"


def test_from_entry_skips_non_image_enclosures():
    entry = {
        "enclosures": [
            {"href": "https://a.com/pod.mp3", "type": "audio/mpeg"},
            {"href": "https://a.com/img.png", "type": "image/png"},
        ],
    }
    assert image_extractor.from_entry(entry) == "https://a.com/img.png"


if __name__ == "__main__":
    for name in list(globals()):
        if name.startswith("test_"):
            globals()[name]()
            print("OK", name)
