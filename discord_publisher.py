"""Build Discord embeds and publish to a channel."""
import asyncio
import logging

import discord

from config import RATE_LIMIT_SECONDS

logger = logging.getLogger(__name__)

COLOR_EN = 0x3498DB
COLOR_IT = 0x2ECC71


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_embed(item: dict) -> discord.Embed:
    color = COLOR_IT if item["language"] == "it" else COLOR_EN
    embed = discord.Embed(
        title=_truncate(item["title"], 256),
        url=item["url"],
        color=color,
        timestamp=item["published"],
    )
    if item["summary"]:
        embed.description = _truncate(item["summary"], 300)
    embed.set_footer(text=f"{item['source']} · {item['language'].upper()}")
    return embed


async def publish(channel: discord.abc.Messageable, items: list[dict]) -> int:
    sent = 0
    for item in items:
        try:
            await channel.send(embed=build_embed(item))
            sent += 1
            await asyncio.sleep(RATE_LIMIT_SECONDS)
        except discord.DiscordException as e:
            logger.error("Invio fallito per %s: %s", item.get("url"), e)
    return sent
