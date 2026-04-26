"""Unit tests for AI curation response parsing."""
import os
import sys

os.environ.setdefault("DISCORD_TOKEN", "x")
os.environ.setdefault("DISCORD_CHANNEL_ID", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_curator  # noqa: E402


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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
