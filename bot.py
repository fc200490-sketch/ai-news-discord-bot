"""Discord AI-news bot entry point."""
import logging

import discord
from discord.ext import tasks

from config import DISCORD_CHANNEL_ID, DISCORD_TOKEN, FETCH_INTERVAL_HOURS
from dedup import load_seen, mark_seen
from discord_publisher import publish
from news_fetcher import fetch_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai-news-bot")

intents = discord.Intents.default()
client = discord.Client(intents=intents)


@tasks.loop(hours=FETCH_INTERVAL_HOURS)
async def news_cycle():
    try:
        channel = client.get_channel(DISCORD_CHANNEL_ID) or await client.fetch_channel(DISCORD_CHANNEL_ID)
    except discord.DiscordException as e:
        logger.error("Canale non raggiungibile: %s", e)
        return

    try:
        items = await fetch_all()
    except Exception as e:
        logger.exception("Errore durante il fetch: %s", e)
        return

    seen = load_seen()
    fresh = [i for i in items if i["url"] not in seen]
    logger.info("Trovate %d notizie, %d nuove", len(items), len(fresh))

    if not fresh:
        return

    sent = await publish(channel, fresh)
    if sent:
        mark_seen([i["url"] for i in fresh[:sent]])
    logger.info("Ciclo completato: pubblicate %d/%d", sent, len(fresh))


@news_cycle.before_loop
async def _before():
    await client.wait_until_ready()


@client.event
async def on_ready():
    logger.info("Bot connesso come %s (id=%s)", client.user, client.user.id)
    if not news_cycle.is_running():
        news_cycle.start()


if __name__ == "__main__":
    client.run(DISCORD_TOKEN, log_handler=None)
