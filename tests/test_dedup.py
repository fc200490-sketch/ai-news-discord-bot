"""Unit tests for dedup primitives — no network, no Discord."""
import os
import sys
import tempfile

os.environ.setdefault("DISCORD_TOKEN", "x")
os.environ.setdefault("DISCORD_CHANNEL_ID", "1")
os.environ.setdefault("STATE_DB_PATH", os.path.join(tempfile.gettempdir(), "test_state.db"))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import embeddings  # noqa: E402
from dedup import find_semantic_duplicate, lexical_similarity, normalize_title  # noqa: E402
from feeds import is_priority  # noqa: E402


def test_normalize_drops_stopwords_and_punct():
    assert normalize_title("The New OpenAI Model!") == "openai model"
    assert normalize_title("Il nuovo modello di OpenAI") == "nuovo modello openai"


def test_lexical_similarity_near_duplicates():
    a = normalize_title("OpenAI releases GPT-5 with new features")
    b = normalize_title("OpenAI launches GPT-5 with new capabilities")
    assert lexical_similarity(a, b) > 0.5


def test_cosine_basic():
    assert embeddings.cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert embeddings.cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert abs(embeddings.cosine([1.0, 1.0], [1.0, 0.0]) - 0.7071) < 0.01
    assert embeddings.cosine(None, [1.0]) == 0.0
    assert embeddings.cosine([1.0], [1.0, 2.0]) == 0.0


def test_find_semantic_duplicate_via_embedding():
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    item = {"title": "OpenAI ships GPT-5", "title_norm": normalize_title("OpenAI ships GPT-5"),
            "embedding": [1.0, 0.0, 0.0]}
    candidates = [
        {"url": "https://x/1", "ts": now_iso, "title_norm": "unrelated",
         "embedding": [0.0, 1.0, 0.0]},
        {"url": "https://x/2", "ts": now_iso, "title_norm": "gpt5 released",
         "embedding": [0.99, 0.01, 0.0]},
    ]
    match = find_semantic_duplicate(item, candidates, 0.9, 0.82, 48)
    assert match is not None and match["url"] == "https://x/2"


def test_find_semantic_duplicate_respects_window():
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    item = {"title": "a", "title_norm": "openai gpt5", "embedding": [1.0, 0.0]}
    candidates = [{"url": "u", "ts": old, "title_norm": "openai gpt5", "embedding": [1.0, 0.0]}]
    assert find_semantic_duplicate(item, candidates, 0.9, 0.82, 48) is None


def test_priority_keywords():
    assert is_priority("OpenAI releases GPT-5")
    assert is_priority("Anthropic raises $5B")
    assert not is_priority("A quiet day in tech")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
