"""RSS feed sources for AI news.

FEEDS_EN: AI-dedicated feeds (all entries assumed on-topic).
FEEDS_IT: generalist Italian feeds (entries must match AI_KEYWORDS to be included).
"""

FEEDS_EN = [
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", True),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", True),
    ("MIT Technology Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed", True),
    ("Ars Technica AI", "https://arstechnica.com/tag/artificial-intelligence/feed/", True),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/", True),
    ("Anthropic", "https://www.anthropic.com/news/rss.xml", True),
    ("OpenAI", "https://openai.com/blog/rss.xml", True),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", True),
]

FEEDS_IT = [
    ("DDAY", "https://www.dday.it/feed", False),
    ("Wired IT", "https://www.wired.it/feed/rss", False),
    ("Il Post", "https://www.ilpost.it/feed/", False),
]

AI_KEYWORDS = [
    "intelligenza artificiale",
    "machine learning",
    "deep learning",
    "chatgpt",
    "openai",
    "anthropic",
    "claude",
    "gemini",
    "deepmind",
    "llm",
    "modello linguistico",
    "generativa",
    "generative ai",
    " ai ",
    "a.i.",
]


def all_feeds():
    """Return list of (source_name, url, is_ai_dedicated, language)."""
    return (
        [(n, u, dedicated, "en") for n, u, dedicated in FEEDS_EN]
        + [(n, u, dedicated, "it") for n, u, dedicated in FEEDS_IT]
    )
