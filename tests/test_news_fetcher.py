"""Unit tests for news_fetcher cache + helpers (no network)."""
import json
import os
import sys
import tempfile
import uuid

os.environ.setdefault("DISCORD_TOKEN", "x")
os.environ.setdefault("DISCORD_CHANNEL_ID", "1")
# Point cache file to a throwaway location BEFORE importing the module.
_cache_path = os.path.join(tempfile.gettempdir(), f"test_feedcache_{uuid.uuid4().hex}.json")
os.environ["FEED_CACHE_FILE"] = _cache_path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import news_fetcher  # noqa: E402


def test_save_and_load_feed_cache():
    data = {"https://feed/a": {"etag": "abc", "last_modified": "Mon"}}
    news_fetcher._save_feed_cache(data)
    assert os.path.exists(_cache_path)
    loaded = news_fetcher._load_feed_cache()
    assert loaded == data


def test_load_missing_cache_returns_empty():
    missing = _cache_path + ".missing"
    old = news_fetcher.FEED_CACHE_FILE
    try:
        news_fetcher.FEED_CACHE_FILE = missing
        assert news_fetcher._load_feed_cache() == {}
    finally:
        news_fetcher.FEED_CACHE_FILE = old


def test_load_corrupted_cache_returns_empty():
    with open(_cache_path, "w", encoding="utf-8") as f:
        f.write("{not valid json")
    assert news_fetcher._load_feed_cache() == {}


def test_save_is_atomic_no_tmp_leftover():
    data = {"https://feed/b": {"etag": "z"}}
    news_fetcher._save_feed_cache(data)
    assert not os.path.exists(_cache_path + ".tmp")
    # Final file must be valid JSON.
    with open(_cache_path, encoding="utf-8") as f:
        assert json.load(f) == data


def test_strip_html_and_collapse():
    out = news_fetcher._strip_html("<p>Hello  <b>world</b></p>")
    assert out == "Hello world"


def test_matches_ai_keyword_positive_negative():
    pos = {"title": "New ChatGPT feature", "summary": "", "tags": []}
    neg = {"title": "Ricetta della carbonara", "summary": "", "tags": []}
    assert news_fetcher._matches_ai(pos) is True
    assert news_fetcher._matches_ai(neg) is False


def test_matches_ai_acronym_case_sensitive():
    # Italian preposition "ai" lowercase must NOT trigger.
    neg = {"title": "Consigli ai genitori", "summary": "", "tags": []}
    pos = {"title": "AI takes over", "summary": "", "tags": []}
    assert news_fetcher._matches_ai(neg) is False
    assert news_fetcher._matches_ai(pos) is True


if __name__ == "__main__":
    for name in list(globals()):
        if name.startswith("test_"):
            globals()[name]()
            print("OK", name)
    try:
        os.remove(_cache_path)
    except OSError:
        pass
