"""Unit tests for AI curation response parsing."""
import os
import sys
import asyncio

os.environ.setdefault("DISCORD_TOKEN", "x")
os.environ.setdefault("DISCORD_CHANNEL_ID", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_curator  # noqa: E402


class _FakeResponse:
    text = '{"keep": true, "score": 88, "reason": "Relevant.", "summary": "Curated."}'


class _FakeModels:
    def generate_content(self, **_kwargs):
        return _FakeResponse()


class _FakeClient:
    models = _FakeModels()


def test_parse_valid_json():
    out = ai_curator._parse_curation_response(
        '{"keep": true, "score": 91, "reason": "Fonte ufficiale.", "summary": "TL;DR"}'
    )
    assert out == {
        "keep": True,
        "score": 91,
        "reason": "Fonte ufficiale.",
        "summary": "TL;DR",
    }


def test_parse_json_with_extra_text():
    out = ai_curator._parse_curation_response(
        'Ecco il JSON: {"keep": false, "score": 22, "reason": "Fuori focus.", "summary": ""}'
    )
    assert out["keep"] is False
    assert out["score"] == 22


def test_parse_clamps_score_and_defaults_keep_from_score():
    out = ai_curator._parse_curation_response(
        '{"score": 120, "reason": "Alta rilevanza", "summary": "News importante"}'
    )
    assert out["score"] == 100
    assert out["keep"] is True


def test_parse_invalid_returns_none():
    assert ai_curator._parse_curation_response("not json") is None


def test_curate_does_not_apply_env_flag_gate():
    old_get_client = ai_curator.get_client
    old_interval = ai_curator.AI_CURATION_MIN_INTERVAL_SECONDS
    had_legacy_flag = hasattr(ai_curator, "ENABLE_AI_CURATION")
    old_legacy_flag = getattr(ai_curator, "ENABLE_AI_CURATION", None)
    try:
        ai_curator.get_client = lambda: _FakeClient()
        ai_curator.AI_CURATION_MIN_INTERVAL_SECONDS = 0
        ai_curator.ENABLE_AI_CURATION = False
        out = asyncio.run(ai_curator.curate({
            "source": "OpenAI",
            "language": "en",
            "title": "Important AI model launch",
            "summary": "A relevant announcement.",
            "url": "https://example.com/news",
        }))
    finally:
        ai_curator.get_client = old_get_client
        ai_curator.AI_CURATION_MIN_INTERVAL_SECONDS = old_interval
        if had_legacy_flag:
            ai_curator.ENABLE_AI_CURATION = old_legacy_flag
        else:
            delattr(ai_curator, "ENABLE_AI_CURATION")

    assert out["keep"] is True
    assert out["score"] == 88


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
