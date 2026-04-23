"""Singleton Gemini client shared by embeddings and summarizer."""
import logging

from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

_client = None
_failed = False


def get_client():
    global _client, _failed
    if _client is not None or _failed:
        return _client
    if not GEMINI_API_KEY:
        _failed = True
        return None
    try:
        from google import genai
        _client = genai.Client(api_key=GEMINI_API_KEY)
        return _client
    except Exception as e:
        logger.warning("Gemini client not initialized: %s", e)
        _failed = True
        return None
