"""RSS feed sources for AI news.

FEEDS_EN: AI-dedicated feeds (all entries assumed on-topic).
FEEDS_IT: generalist Italian feeds (entries must match AI_KEYWORDS to be included).
"""
import re

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

# Keywords used to filter generalist Italian feeds. Matched as whole words
# (word-boundary regex) so "ai" doesn't accidentally match "aiuta", etc.
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
    "ai",
    "a.i.",
    "mistral",
    "meta ai",
    "grok",
]

# Keywords that, when present in title or summary, flag the news as high-priority.
# Rendered as a 🔥 prefix in the embed title.
PRIORITY_KEYWORDS = [
    "gpt-5", "gpt-6", "claude 5", "claude 4.5", "claude 4.6",
    "gemini 2", "gemini 3",
    "acquisition", "acquires", "acquisisce",
    "funding", "raises", "raccoglie",
    "lawsuit", "causa legale",
    "launch", "launches", "release", "releases", "rilascia", "presenta",
    "breakthrough",
]


def _compile(keywords: list[str]) -> re.Pattern:
    escaped = []
    for kw in keywords:
        if not kw:
            continue
        # Allow arbitrary whitespace between tokens, anchor at word boundaries.
        parts = [re.escape(tok) for tok in kw.split()]
        escaped.append(r"\b" + r"\s+".join(parts) + r"\b")
    if not escaped:
        return re.compile(r"(?!x)x")  # never matches
    return re.compile("|".join(escaped), flags=re.IGNORECASE)


AI_KEYWORDS_RE = _compile(AI_KEYWORDS)
PRIORITY_KEYWORDS_RE = _compile(PRIORITY_KEYWORDS)


def all_feeds():
    """Return list of (source_name, url, is_ai_dedicated, language)."""
    return (
        [(n, u, dedicated, "en") for n, u, dedicated in FEEDS_EN]
        + [(n, u, dedicated, "it") for n, u, dedicated in FEEDS_IT]
    )


def is_priority(text: str) -> bool:
    return bool(text) and bool(PRIORITY_KEYWORDS_RE.search(text))
