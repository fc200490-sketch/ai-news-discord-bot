"""Unit tests for storage layer — uses a throwaway SQLite DB."""
import os
import sys
import tempfile
import uuid

os.environ.setdefault("DISCORD_TOKEN", "x")
os.environ.setdefault("DISCORD_CHANNEL_ID", "1")
os.environ["STATE_DB_PATH"] = os.path.join(
    tempfile.gettempdir(), f"test_storage_{uuid.uuid4().hex}.db"
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storage  # noqa: E402

storage.init()


def test_mark_posted_and_get_urls():
    storage.mark_posted([
        {"url": "https://a/1", "title_norm": "hello world", "embedding": None, "source": "A"},
        {"url": "https://b/2", "title_norm": "foo bar", "embedding": [0.1, 0.2], "source": "B"},
    ])
    urls = storage.get_posted_urls()
    assert "https://a/1" in urls
    assert "https://b/2" in urls


def test_load_recent_posted_roundtrips_embedding():
    storage.mark_posted([
        {"url": "https://c/3", "title_norm": "x", "embedding": [1.0, 2.0, 3.0], "source": "C"},
    ])
    rows = storage.load_recent_posted(window_hours=24)
    match = [r for r in rows if r["url"] == "https://c/3"]
    assert len(match) == 1
    assert match[0]["embedding"] == [1.0, 2.0, 3.0]
    assert match[0]["source"] == "C"


def test_muted_source_roundtrip():
    chan = 9999
    storage.add_muted_source(chan, "Foo")
    assert "Foo" in storage.list_muted_sources(chan)
    assert storage.remove_muted_source(chan, "Foo") is True
    assert storage.remove_muted_source(chan, "Foo") is False
    assert "Foo" not in storage.list_muted_sources(chan)


def test_register_and_get_message():
    storage.register_message(42, "https://x/1", "SrcX", title="T", excerpt="E")
    assert storage.get_message_source(42) == "SrcX"
    assert storage.get_message_content(42) == ("T", "E")
    assert storage.get_extended_summary(42) is None
    storage.set_extended_summary(42, "long text")
    assert storage.get_extended_summary(42) == "long text"


def test_source_stats_clamp_at_zero():
    storage.bump_source_stat("SrcY", 1, 0)
    storage.bump_source_stat("SrcY", -5, 0)  # should clamp at 0
    stats = storage.get_source_stats()
    assert stats["SrcY"]["up"] == 0


if __name__ == "__main__":
    test_mark_posted_and_get_urls()
    print("OK test_mark_posted_and_get_urls")
    test_load_recent_posted_roundtrips_embedding()
    print("OK test_load_recent_posted_roundtrips_embedding")
    test_muted_source_roundtrip()
    print("OK test_muted_source_roundtrip")
    test_register_and_get_message()
    print("OK test_register_and_get_message")
    test_source_stats_clamp_at_zero()
    print("OK test_source_stats_clamp_at_zero")
