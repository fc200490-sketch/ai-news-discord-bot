"""Environment configuration."""
import os
import sys

from dotenv import load_dotenv

load_dotenv()

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
STATE_FILE = "posted_urls.json"
STATE_TTL_DAYS = 14
RATE_LIMIT_SECONDS = 1.5
