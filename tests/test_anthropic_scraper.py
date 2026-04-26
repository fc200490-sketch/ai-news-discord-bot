"""Unit tests for Anthropic news HTML extraction."""
import os
import sys

os.environ.setdefault("DISCORD_TOKEN", "x")
os.environ.setdefault("DISCORD_CHANNEL_ID", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic_scraper  # noqa: E402


def test_extract_relative_heading_card():
    html = """
    <a href="/news/claude-update">
      <article>
        <time>Apr 20, 2026</time>
        <h2>Claude update ships</h2>
        <p>Short excerpt.</p>
      </article>
    </a>
    """
    items = anthropic_scraper._extract(html)
    assert len(items) == 1
    assert items[0]["title"] == "Claude update ships"
    assert items[0]["url"] == "https://www.anthropic.com/news/claude-update"
    assert items[0]["summary"] == "Short excerpt."


def test_extract_absolute_span_title_and_datetime():
    html = """
    <a href="https://www.anthropic.com/news/model-card">
      <time datetime="2026-04-21T10:30:00Z">ignored</time>
      <span class="news-title">Model card released</span>
    </a>
    """
    items = anthropic_scraper._extract(html)
    assert len(items) == 1
    assert items[0]["title"] == "Model card released"
    assert items[0]["published"].isoformat() == "2026-04-21T10:30:00+00:00"


def test_extract_full_month_date_from_parent():
    html = """
    <div>
      <time>April 22, 2026</time>
      <a href="/news/safety-note">
        <span class="title">Safety note published</span>
      </a>
    </div>
    """
    items = anthropic_scraper._extract(html)
    assert len(items) == 1
    assert items[0]["published"].isoformat() == "2026-04-22T00:00:00+00:00"


def test_extract_deduplicates_normalized_urls():
    html = """
    <a href="/news/same-story"><time>Apr 20, 2026</time><h3>Same story</h3></a>
    <a href="https://www.anthropic.com/news/same-story">
      <time>Apr 20, 2026</time><h3>Same story duplicate</h3>
    </a>
    """
    items = anthropic_scraper._extract(html)
    assert len(items) == 1
    assert items[0]["url"] == "https://www.anthropic.com/news/same-story"


def test_extract_ignores_non_news_and_other_hosts():
    html = """
    <a href="/news"><time>Apr 20, 2026</time><h3>Index</h3></a>
    <a href="https://example.com/news/fake"><time>Apr 20, 2026</time><h3>Fake</h3></a>
    <a href="/company"><time>Apr 20, 2026</time><h3>Company</h3></a>
    """
    assert anthropic_scraper._extract(html) == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
