"""Build Discord embeds and publish via digest + thread."""
import asyncio
import logging
import re
import time
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

COLOR_EN = 0x3498DB  # blue
COLOR_IT = 0x2ECC71  # green
COLOR_DEFAULT = 0x95A5A6  # grey
_LANG_COLORS = {
    "en": COLOR_EN,
    "it": COLOR_IT,
    "es": 0xE67E22,  # orange
    "fr": 0x9B59B6,  # purple
    "de": 0xF1C40F,  # yellow
    "pt": 0x1ABC9C,  # teal
}

FEEDBACK_UP = "👍"
FEEDBACK_DOWN = "👎"
_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)

# Per-(message, user) cooldown for "Leggi di più" to prevent spam even if the
# extended summary is cached (avoid rapid-fire ephemeral replies).
_READMORE_COOLDOWN_S = 5.0
_READMORE_TTL_S = 60.0  # purge stale entries after this long
_readmore_last_click: dict[tuple[int, int], float] = {}


def _gc_readmore_clicks(now: float) -> None:
    """Drop entries older than TTL to bound memory growth."""
    cutoff = now - _READMORE_TTL_S
    stale = [k for k, ts in _readmore_last_click.items() if ts < cutoff]
    for k in stale:
        _readmore_last_click.pop(k, None)


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


READMORE_CUSTOM_ID = "news:readmore"


class ReadMoreView(discord.ui.View):
    """Persistent view with a single "Leggi di più" button backed by a static
    custom_id. The article link is already reachable via the embed title."""

    def __init__(self, item: dict | None = None):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Leggi di più",
        style=discord.ButtonStyle.secondary,
        custom_id=READMORE_CUSTOM_ID,
    )
    async def read_more(self, interaction: discord.Interaction, _button: discord.ui.Button):
        msg_id = interaction.message.id if interaction.message else 0
        user_id = interaction.user.id if interaction.user else 0
        now = time.monotonic()
        _gc_readmore_clicks(now)
        key = (msg_id, user_id)
        last = _readmore_last_click.get(key, 0.0)
        if now - last < _READMORE_COOLDOWN_S:
            await interaction.response.send_message(
                "Un attimo, troppe richieste ravvicinate.", ephemeral=True,
            )
            return
        _readmore_last_click[key] = now

        await interaction.response.defer(ephemeral=True, thinking=True)

        # Served-from-cache path: avoid Gemini call entirely.
        cached = storage.get_extended_summary(msg_id)
        if cached:
            await interaction.followup.send(content=_truncate(cached, 1800), ephemeral=True)
            return

        content = storage.get_message_content(msg_id)
        if not content:
            await interaction.followup.send(
                "Dati non più disponibili per questo messaggio.", ephemeral=True,
            )
            return
        title, excerpt = content
        text = await ai_summarizer.summarize_extended(title, excerpt)
        if text:
            try:
                storage.set_extended_summary(msg_id, text)
            except Exception as e:
                logger.debug("Cache extended_summary failed: %s", e)
        text = text or excerpt or "Nessun dettaglio disponibile."
        await interaction.followup.send(content=_truncate(text, 1800), ephemeral=True)


def build_embed(item: dict) -> discord.Embed:
    color = _LANG_COLORS.get(item.get("language", ""), COLOR_DEFAULT)
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

    curation_reason = item.get("curation_reason")
    if curation_reason:
        embed.add_field(
            name="Perché conta",
            value=_truncate(curation_reason, 300),
            inline=False,
        )

    also_on = item.get("also_on") or []
    if also_on:
        embed.add_field(
            name="Anche su",
            value=_truncate(", ".join(also_on), 1024),
            inline=False,
        )

    reading = _reading_time_minutes(item)
    # "TL;DR" because the count is on the embed description, not on the
    # original article — avoid misleading the reader.
    footer = f"{item['source']} · {item['language'].upper()} · ~{reading} min TL;DR"
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
    except discord.DiscordException as e:
        logger.error("Send failed for %s: %s", item.get("url"), e)
        return None
    # Persist BEFORE any awaitable work: register + mark_posted are synchronous
    # SQLite calls, so no CancelledError can sneak in between target.send and
    # mark_posted. Reactions (awaitable) come AFTER persistence.
    try:
        storage.register_message(
            msg.id, item["url"], item.get("source", ""),
            title=item.get("title", ""),
            excerpt=item.get("summary") or "",
        )
    except Exception as e:
        logger.warning("register_message failed for %s: %s", msg.id, e)
    try:
        storage.mark_posted([{
            "url": item["url"],
            "title_norm": item.get("title_norm") or "",
            "embedding": item.get("embedding"),
            "source": item.get("source", ""),
        }])
    except Exception as e:
        logger.warning("mark_posted per-item failed for %s: %s", msg.id, e)
    # Reactions are a nice-to-have; failures (including cancellation) don't
    # roll back the already-persisted post.
    if ENABLE_REACTION_FEEDBACK:
        try:
            await msg.add_reaction(FEEDBACK_UP)
            await msg.add_reaction(FEEDBACK_DOWN)
        except Exception as e:
            logger.debug("Add reactions failed: %s", e)
    return msg


async def publish(channel: discord.abc.Messageable, items: list[dict]) -> list[dict]:
    """Send items; return the subset actually delivered.

    When ENABLE_THREAD_DIGEST is true and the channel supports threads, opens
    a thread from a digest header and posts each news inside it. Otherwise
    sends flat into the channel.
    """
    if not items:
        return []

    target = channel
    if ENABLE_THREAD_DIGEST and isinstance(channel, discord.TextChannel):
        try:
            header = await channel.send(_digest_header(items))
            target = await header.create_thread(
                name=f"AI News {datetime.now(timezone.utc).astimezone().strftime('%d/%m %H:%M')}",
                auto_archive_duration=1440,
            )
        except discord.DiscordException as e:
            logger.warning("Thread digest failed, falling back to flat channel: %s", e)
            target = channel

    sent: list[dict] = []
    for item in items:
        msg = await _send_one(target, item)
        if msg:
            sent.append(item)
        await asyncio.sleep(RATE_LIMIT_SECONDS)
    return sent
