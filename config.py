"""Environment configuration."""
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
_channel_id_raw = os.getenv("DISCORD_CHANNEL_ID")

if not DISCORD_TOKEN:
    sys.exit("ERROR: DISCORD_TOKEN non impostato. Configura la variabile d'ambiente o il file .env")

if not _channel_id_raw:
    sys.exit("ERROR: DISCORD_CHANNEL_ID non impostato.")

try:
    DISCORD_CHANNEL_ID = int(_channel_id_raw)
except ValueError:
    sys.exit("ERROR: DISCORD_CHANNEL_ID deve essere un intero (ID numerico del canale).")

FETCH_INTERVAL_HOURS = 12
LOOKBACK_HOURS = 12
# Optional: "HH:MM,HH:MM" in UTC. If set, overrides FETCH_INTERVAL_HOURS and the
# bot publishes at those fixed wall-clock times each day.
FETCH_TIMES_UTC = os.getenv("FETCH_TIMES_UTC", "").strip()
STATE_DB_PATH = os.getenv("STATE_DB_PATH", "state.db").strip() or "state.db"
LEGACY_STATE_FILE = "posted_urls.json"
FEED_CACHE_FILE = os.getenv("FEED_CACHE_FILE", ".feed_cache.json").strip() or ".feed_cache.json"
STATE_TTL_DAYS = 14
FEEDBACK_TTL_DAYS = 45
RATE_LIMIT_SECONDS = 1.5

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip() or None
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001").strip()

ENABLE_AI_SUMMARY = _env_bool("ENABLE_AI_SUMMARY", True) and GEMINI_API_KEY is not None
ENABLE_SMART_DEDUP = _env_bool("ENABLE_SMART_DEDUP", True)
ENABLE_THUMBNAILS = _env_bool("ENABLE_THUMBNAILS", True)
ENABLE_FEED_RETRY = _env_bool("ENABLE_FEED_RETRY", True)
ENABLE_EMBEDDING_DEDUP = _env_bool("ENABLE_EMBEDDING_DEDUP", True) and GEMINI_API_KEY is not None
ENABLE_THREAD_DIGEST = _env_bool("ENABLE_THREAD_DIGEST", True)
ENABLE_READ_MORE = _env_bool("ENABLE_READ_MORE", True) and GEMINI_API_KEY is not None
ENABLE_REACTION_FEEDBACK = _env_bool("ENABLE_REACTION_FEEDBACK", True)

SIMILARITY_THRESHOLD = _env_float("SIMILARITY_THRESHOLD", 0.82)
EMBEDDING_SIMILARITY_THRESHOLD = _env_float("EMBEDDING_SIMILARITY_THRESHOLD", 0.88)
DEDUP_WINDOW_HOURS = _env_int("DEDUP_WINDOW_HOURS", 48)

AI_SUMMARY_CONCURRENCY = _env_int("AI_SUMMARY_CONCURRENCY", 1)
AI_SUMMARY_MIN_INTERVAL_SECONDS = _env_float("AI_SUMMARY_MIN_INTERVAL_SECONDS", 13.0)
EMBEDDING_CONCURRENCY = _env_int("EMBEDDING_CONCURRENCY", 2)
EMBEDDING_MIN_INTERVAL_SECONDS = _env_float("EMBEDDING_MIN_INTERVAL_SECONDS", 0.5)
SUMMARY_LANGUAGE = os.getenv("SUMMARY_LANGUAGE", "it").strip().lower() or "it"

NEWS_NOW_COOLDOWN_SECONDS = _env_int("NEWS_NOW_COOLDOWN_SECONDS", 300)
READING_WPM = _env_int("READING_WPM", 200)
