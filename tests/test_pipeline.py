"""End-to-end test for the prefilter+semantic_group pipeline in bot.py."""
import os
import sys
import tempfile
import asyncio
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

import bot  # noqa: E402
from bot import _apply_ai_curation, _prefilter, _semantic_group, _sort_for_digest  # noqa: E402


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


def test_prefilter_drops_global_muted_source():
    storage.add_global_muted_source("GlobalBanned")
    fresh = [
        _item("A", "https://global/1", source="GlobalBanned"),
        _item("B", "https://global/2", source="OK"),
    ]
    out = _prefilter(fresh, channel_id=999)
    sources = [i["source"] for i in out]
    assert "GlobalBanned" not in sources
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


def test_ai_curation_drops_low_score_and_keeps_high_score():
    async def fake_curate(item):
        if "important" in item["title"].lower():
            return {
                "keep": True,
                "score": 91,
                "reason": "Important AI development.",
                "summary": "Curated summary.",
            }
        return {
            "keep": False,
            "score": 30,
            "reason": "Low relevance.",
            "summary": "",
        }

    old_enabled = bot.ENABLE_AI_CURATION
    old_curate = bot.ai_curator.curate
    try:
        bot.ENABLE_AI_CURATION = True
        bot.ai_curator.curate = fake_curate
        items = [
            _item("Important AI agent launch", "https://e/1", source="OpenAI"),
            _item("Generic gadget rumor", "https://e/2", source="Blog"),
        ]
        kept = asyncio.run(_apply_ai_curation(items))
    finally:
        bot.ENABLE_AI_CURATION = old_enabled
        bot.ai_curator.curate = old_curate

    assert len(kept) == 1
    assert kept[0]["url"] == "https://e/1"
    assert kept[0]["summary_ai"] == "Curated summary."
    assert kept[0]["curation_reason"] == "Important AI development."


def test_ai_curation_uses_runtime_min_score():
    async def fake_curate(_item):
        return {
            "keep": True,
            "score": 75,
            "reason": "Useful but not critical.",
            "summary": "Curated summary.",
        }

    old_enabled = bot.ENABLE_AI_CURATION
    old_curate = bot.ai_curator.curate
    old_key = bot.GEMINI_API_KEY
    try:
        bot.ENABLE_AI_CURATION = True
        bot.GEMINI_API_KEY = "x"
        bot.ai_curator.curate = fake_curate
        storage.set_setting(bot.SETTING_AI_CURATION_MIN_SCORE, "80")
        kept = asyncio.run(_apply_ai_curation([_item("Medium score", "https://score/1")]))
    finally:
        bot.ENABLE_AI_CURATION = old_enabled
        bot.GEMINI_API_KEY = old_key
        bot.ai_curator.curate = old_curate
        storage.delete_setting(bot.SETTING_AI_CURATION_MIN_SCORE)

    assert kept == []


def test_ai_curation_runtime_disabled_skips_curator():
    async def fail_if_called(_item):
        raise AssertionError("curator should not be called")

    old_enabled = bot.ENABLE_AI_CURATION
    old_curate = bot.ai_curator.curate
    old_key = bot.GEMINI_API_KEY
    try:
        bot.ENABLE_AI_CURATION = True
        bot.GEMINI_API_KEY = "x"
        bot.ai_curator.curate = fail_if_called
        storage.set_setting(bot.SETTING_AI_CURATION_ENABLED, "false")
        items = [_item("Runtime disabled", "https://disabled/1")]
        kept = asyncio.run(_apply_ai_curation(items))
    finally:
        bot.ENABLE_AI_CURATION = old_enabled
        bot.GEMINI_API_KEY = old_key
        bot.ai_curator.curate = old_curate
        storage.delete_setting(bot.SETTING_AI_CURATION_ENABLED)

    assert len(kept) == 1
    assert kept[0]["url"] == "https://disabled/1"


def test_ai_curation_fallback_keeps_items_when_curator_fails():
    async def fake_curate(_item):
        return None

    old_enabled = bot.ENABLE_AI_CURATION
    old_curate = bot.ai_curator.curate
    try:
        bot.ENABLE_AI_CURATION = True
        bot.ai_curator.curate = fake_curate
        items = [_item("Fallback item", "https://f/1")]
        kept = asyncio.run(_apply_ai_curation(items))
    finally:
        bot.ENABLE_AI_CURATION = old_enabled
        bot.ai_curator.curate = old_curate

    assert len(kept) == 1
    assert kept[0]["url"] == "https://f/1"


def test_sort_for_digest_prioritizes_score_over_freshness():
    older_high = _item("Important model launch", "https://g/1", source="OpenAI")
    newer_low = _item("Minor update", "https://g/2", source="Blog")
    older_high["curation_score"] = 92
    newer_low["curation_score"] = 71
    ordered = _sort_for_digest([newer_low, older_high])
    assert ordered[0]["url"] == "https://g/1"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
