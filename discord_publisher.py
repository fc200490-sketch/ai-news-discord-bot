"""Build Discord embeds and publish via digest + thread."""
import asyncio
import logging
import re
from datetime import datetime, timezone

import discord

import ai_summarizer
import storage
from config import (
    ENABLE_READ_MORE,
    ENABLE_REACTION_FEEDBACK,
    ENABLE_THREAD_DIGEST,
    RATE_LIMIT_SECONDS,
    READING_WPM,
)
from feeds import is_priority

logger = logging.getLogger(__name__)

COLOR_EN = 0x3498DB
COLOR_IT = 0x2ECC71
COLOR_DIGEST = 0x5865F2

FEEDBACK_UP = "👍"
FEEDBACK_DOWN = "👎"
_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _reading_time_minutes(item: dict) -> int:
    blob = " ".join([item.get("summary") or "", item.get("summary_ai") or ""])
    words = len(_WORD_RE.findall(blob))
    if words < 30:
        words = 250  # estimate article length when excerpt is tiny
    minutes = max(1, round(words / max(1, READING_WPM)))
    return minutes


class ReadMoreView(discord.ui.View):
    def __init__(self, item: dict):
        super().__init__(timeout=None)
        self._item = item
        self._cached: str | None = None
        link_btn = discord.ui.Button(
            label="Apri articolo",
            style=discord.ButtonStyle.link,
            url=item["url"],
        )
        self.add_item(link_btn)

    @discord.ui.button(label="Leggi di più", style=discord.ButtonStyle.secondary)
    async def read_more(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not self._cached:
            self._cached = await ai_summarizer.summarize_extended(
                self._item.get("title", ""),
                self._item.get("summary") or "",
            )
        text = self._cached or self._item.get("summary") or "Nessun dettaglio disponibile."
        await interaction.followup.send(content=_truncate(text, 1800), ephemeral=True)


def build_embed(item: dict) -> discord.Embed:
    color = COLOR_IT if item["language"] == "it" else COLOR_EN
    title = item["title"]
    if is_priority(title + " " + (item.get("summary") or "")):
        title = f"🔥 {title}"
    embed = discord.Embed(
        title=_truncate(title, 256),
        url=item["url"],
        color=color,
        timestamp=item["published"],
    )
    description = item.get("summary_ai") or item.get("summary") or ""
    if description:
        embed.description = _truncate(description, 400)
    thumbnail = item.get("thumbnail_url")
    if thumbnail:
        embed.set_image(url=thumbnail)

    also_on = item.get("also_on") or []
    if also_on:
        embed.add_field(
            name="Anche su",
            value=_truncate(", ".join(also_on), 1024),
            inline=False,
        )

    reading = _reading_time_minutes(item)
    footer = f"{item['source']} · {item['language'].upper()} · ~{reading} min lettura"
    embed.set_footer(text=footer)
    return embed


def _digest_header(items: list[dict]) -> str:
    now = datetime.now(timezone.utc).astimezone()
    when = now.strftime("%d/%m %H:%M")
    priorities = sum(
        1 for i in items if is_priority(i["title"] + " " + (i.get("summary") or ""))
    )
    extra = f" · {priorities} 🔥" if priorities else ""
    return f"📰 **AI News — {when}** · {len(items)} notizie{extra}"


async def _send_one(
    target: discord.abc.Messageable,
    item: dict,
) -> discord.Message | None:
    embed = build_embed(item)
    view = ReadMoreView(item) if ENABLE_READ_MORE else None
    try:
        msg = await target.send(embed=embed, view=view) if view else await target.send(embed=embed)
        if ENABLE_REACTION_FEEDBACK:
            try:
                await msg.add_reaction(FEEDBACK_UP)
                await msg.add_reaction(FEEDBACK_DOWN)
            except discord.DiscordException as e:
                logger.debug("Reactions add fallito: %s", e)
        storage.register_message(msg.id, item["url"], item.get("source", ""))
        return msg
    except discord.DiscordException as e:
        logger.error("Invio fallito per %s: %s", item.get("url"), e)
        return None


async def publish(channel: discord.abc.Messageable, items: list[dict]) -> list[dict]:
    """Send items; return the subset actually delivered.

    When ENABLE_THREAD_DIGEST is true and the channel supports threads, opens
    a thread from a digest header and posts each news inside it. Otherwise
    sends flat into the channel.
    """
    if not items:
        return []

    target = channel
    thread = None
    if ENABLE_THREAD_DIGEST and isinstance(channel, discord.TextChannel):
        try:
            header = await channel.send(_digest_header(items))
            thread = await header.create_thread(
                name=f"AI News {datetime.now(timezone.utc).astimezone().strftime('%d/%m %H:%M')}",
                auto_archive_duration=1440,
            )
            target = thread
        except discord.DiscordException as e:
            logger.warning("Thread digest fallito, uso canale piatto: %s", e)
            target = channel

    sent: list[dict] = []
    for item in items:
        msg = await _send_one(target, item)
        if msg:
            sent.append(item)
        await asyncio.sleep(RATE_LIMIT_SECONDS)
    return sent
