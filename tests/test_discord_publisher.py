"""Unit tests for Discord embed construction."""
import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("DISCORD_TOKEN", "x")
os.environ.setdefault("DISCORD_CHANNEL_ID", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discord_publisher import build_embed  # noqa: E402


def _item(**overrides):
    item = {
        "title": "Anthropic created a test marketplace for agent-on-agent commerce",
        "url": "https://example.com/story",
        "summary": "A short excerpt.",
        "summary_ai": "A concise summary.",
        "source": "Anthropic",
        "published": datetime.now(timezone.utc),
        "language": "en",
        "thumbnail_url": None,
    }
    item.update(overrides)
    return item


def test_build_embed_adds_curation_reason_field():
    embed = build_embed(_item(curation_reason="Shows a real agent commerce experiment."))
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Perché conta"] == "Shows a real agent commerce experiment."


def test_build_embed_omits_curation_reason_when_missing():
    embed = build_embed(_item())
    fields = {field.name: field.value for field in embed.fields}
    assert "Perché conta" not in fields


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
