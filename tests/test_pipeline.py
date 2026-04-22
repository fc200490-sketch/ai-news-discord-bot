"""End-to-end test for the prefilter+semantic_group pipeline in bot.py."""
import os
import sys
import tempfile
from datetime import datetime, timezone

os.environ.setdefault("DISCORD_TOKEN", "x")
os.environ.setdefault("DISCORD_CHANNEL_ID", "1")
os.environ["STATE_DB_PATH"] = os.path.join(tempfile.gettempdir(), "test_pipeline_state.db")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storage  # noqa: E402

# Fresh DB for each run.
if os.path.exists(os.environ["STATE_DB_PATH"]):
    os.remove(os.environ["STATE_DB_PATH"])
storage.init()

from bot import _prefilter, _semantic_group  # noqa: E402


def _item(title: str, url: str, source: str = "TestSrc", lang: str = "en") -> dict:
    return {
        "title": title,
        "url": url,
        "summary": "",
        "source": source,
        "published": datetime.now(timezone.utc),
        "language": lang,
        "thumbnail_url": None,
    }


def test_prefilter_drops_already_posted():
    storage.mark_posted([{"url": "https://a/1", "title_norm": "x", "source": "S"}])
    fresh = [_item("A", "https://a/1"), _item("B", "https://a/2")]
    out = _prefilter(fresh, channel_id=0)
    urls = [i["url"] for i in out]
    assert "https://a/1" not in urls
    assert "https://a/2" in urls


def test_prefilter_drops_muted_source():
    storage.add_muted_source(42, "Banned")
    fresh = [_item("A", "https://b/1", source="Banned"), _item("B", "https://b/2", source="OK")]
    out = _prefilter(fresh, channel_id=42)
    sources = [i["source"] for i in out]
    assert "Banned" not in sources
    assert "OK" in sources


def test_semantic_group_merges_duplicates_intra_cycle():
    # Lexical fallback threshold is 0.82; use near-identical titles.
    a = _item("OpenAI releases new GPT-5 model today", "https://c/1", source="SrcA")
    b = _item("OpenAI releases the GPT-5 model today", "https://c/2", source="SrcB")
    from dedup import normalize_title
    a["title_norm"] = normalize_title(a["title"])
    b["title_norm"] = normalize_title(b["title"])
    kept = _semantic_group([a, b])
    assert len(kept) == 1, f"expected grouped into 1, got {len(kept)}"
    also = kept[0].get("also_on") or []
    assert also, "expected also_on to be populated with merged source"


def test_semantic_group_keeps_unrelated():
    from dedup import normalize_title
    a = _item("Apple Vision Pro review", "https://d/1")
    b = _item("Tesla stock drops today", "https://d/2")
    a["title_norm"] = normalize_title(a["title"])
    b["title_norm"] = normalize_title(b["title"])
    kept = _semantic_group([a, b])
    assert len(kept) == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
