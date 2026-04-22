"""Discord AI-news bot entry point."""
import asyncio
import logging
import time

import discord
from discord import app_commands
from discord.ext import tasks

import ai_summarizer
import embeddings
import storage
from config import (
    DEDUP_WINDOW_HOURS,
    DISCORD_CHANNEL_ID,
    DISCORD_TOKEN,
    EMBEDDING_SIMILARITY_THRESHOLD,
    ENABLE_AI_SUMMARY,
    ENABLE_EMBEDDING_DEDUP,
    ENABLE_REACTION_FEEDBACK,
    ENABLE_SMART_DEDUP,
    FETCH_INTERVAL_HOURS,
    NEWS_NOW_COOLDOWN_SECONDS,
    SIMILARITY_THRESHOLD,
)
from dedup import (
    find_semantic_duplicate,
    get_posted_urls,
    load_seen_recent,
    mark_seen,
    normalize_title,
)
from discord_publisher import FEEDBACK_DOWN, FEEDBACK_UP, publish
from feeds import FEEDS_EN, FEEDS_IT
from news_fetcher import fetch_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai-news-bot")

intents = discord.Intents.default()
intents.reactions = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

_last_news_now: dict[int, float] = {}
_cycle_lock = asyncio.Lock()

ALL_SOURCE_NAMES = sorted({n for n, *_ in FEEDS_EN} | {n for n, *_ in FEEDS_IT})


async def _compute_embeddings(items: list[dict]) -> None:
    if not ENABLE_EMBEDDING_DEDUP:
        return
    coros = [embeddings.embed(it["title"]) for it in items]
    results = await asyncio.gather(*coros, return_exceptions=True)
    for item, res in zip(items, results):
        if isinstance(res, Exception) or res is None:
            continue
        item["embedding"] = res


def _filter_and_group(fresh: list[dict], channel_id: int) -> list[dict]:
    """URL dedup + semantic dedup + muted source filter + multi-source grouping."""
    posted_urls = get_posted_urls()
    muted = set(storage.list_muted_sources(channel_id))

    candidates: list[dict] = []
    for item in fresh:
        if item["url"] in posted_urls:
            continue
        if item.get("source") in muted:
            continue
        item["title_norm"] = normalize_title(item["title"])
        candidates.append(item)

    if not ENABLE_SMART_DEDUP:
        return candidates

    seen_recent = load_seen_recent(DEDUP_WINDOW_HOURS)
    kept: list[dict] = []

    for item in candidates:
        # vs already-posted (cross-cycle): discard, can't retro-edit old messages
        match = find_semantic_duplicate(
            item, seen_recent,
            EMBEDDING_SIMILARITY_THRESHOLD, SIMILARITY_THRESHOLD,
            DEDUP_WINDOW_HOURS,
        )
        if match:
            logger.info("Scartato (già visto): %r ≈ %s", item["title"], match["url"])
            continue

        # vs kept intra-cycle: merge sources instead of discarding
        kept_as_candidates = [
            {
                "url": k["url"], "ts": k["published"].isoformat(),
                "title_norm": k["title_norm"], "embedding": k.get("embedding"),
            }
            for k in kept
        ]
        match = find_semantic_duplicate(
            item, kept_as_candidates,
            EMBEDDING_SIMILARITY_THRESHOLD, SIMILARITY_THRESHOLD,
            DEDUP_WINDOW_HOURS,
        )
        if match:
            for k in kept:
                if k["url"] == match["url"]:
                    k.setdefault("also_on", [])
                    src = item.get("source")
                    if src and src not in k["also_on"] and src != k.get("source"):
                        k["also_on"].append(src)
                    logger.info(
                        "Raggruppato: %r da %s confluisce in %s",
                        item["title"], src, k["url"],
                    )
                    break
            continue

        kept.append(item)
    return kept


async def _attach_summaries(items: list[dict]) -> None:
    if not ENABLE_AI_SUMMARY or not items:
        return
    coros = [
        ai_summarizer.summarize(it["title"], it.get("summary", ""), it["language"])
        for it in items
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)
    for item, res in zip(items, results):
        if isinstance(res, Exception):
            logger.warning("Summarize eccezione per %s: %s", item.get("url"), res)
            continue
        if res:
            item["summary_ai"] = res


async def run_cycle(channel: discord.abc.Messageable) -> dict:
    """Run one fetch→dedup→publish cycle. Returns stats dict."""
    async with _cycle_lock:
        try:
            items = await fetch_all()
        except Exception as e:
            logger.exception("Errore durante il fetch: %s", e)
            return {"error": str(e), "sent": 0}

        await _compute_embeddings(items)

        channel_id = getattr(channel, "id", 0)
        fresh = _filter_and_group(items, channel_id)
        logger.info("%d fetched → %d dopo dedup/grouping", len(items), len(fresh))

        if not fresh:
            return {"fetched": len(items), "sent": 0}

        await _attach_summaries(fresh)

        sent = await publish(channel, fresh)
        if sent:
            mark_seen(sent)
        logger.info("Ciclo: pubblicate %d/%d", len(sent), len(fresh))
        return {"fetched": len(items), "kept": len(fresh), "sent": len(sent)}


@tasks.loop(hours=FETCH_INTERVAL_HOURS)
async def news_cycle():
    try:
        channel = client.get_channel(DISCORD_CHANNEL_ID) or await client.fetch_channel(DISCORD_CHANNEL_ID)
    except discord.DiscordException as e:
        logger.error("Canale non raggiungibile: %s", e)
        return
    await run_cycle(channel)


@news_cycle.before_loop
async def _before():
    await client.wait_until_ready()


# --- Slash commands ---

@tree.command(name="news-now", description="Forza un ciclo di news immediato (admin).")
async def news_now(interaction: discord.Interaction):
    if not (interaction.user.guild_permissions.manage_guild if interaction.guild else False):
        await interaction.response.send_message(
            "Serve il permesso **Manage Server**.", ephemeral=True,
        )
        return
    now = time.monotonic()
    last = _last_news_now.get(interaction.channel_id or 0, 0.0)
    remaining = NEWS_NOW_COOLDOWN_SECONDS - (now - last)
    if remaining > 0:
        await interaction.response.send_message(
            f"Cooldown attivo: riprova tra {int(remaining)}s.", ephemeral=True,
        )
        return
    _last_news_now[interaction.channel_id or 0] = now
    await interaction.response.send_message("Ciclo in esecuzione…", ephemeral=True)
    stats = await run_cycle(interaction.channel)
    await interaction.followup.send(
        f"Fatto. Fetched: {stats.get('fetched', 0)} · "
        f"Da pubblicare: {stats.get('kept', 0)} · Pubblicate: {stats.get('sent', 0)}",
        ephemeral=True,
    )


async def _source_autocomplete(_interaction, current: str):
    current = (current or "").lower()
    return [
        app_commands.Choice(name=s, value=s)
        for s in ALL_SOURCE_NAMES
        if current in s.lower()
    ][:25]


@tree.command(name="mute-source", description="Silenzia una fonte in questo canale.")
@app_commands.describe(source="Nome esatto della fonte da silenziare")
@app_commands.autocomplete(source=_source_autocomplete)
async def mute_source_cmd(interaction: discord.Interaction, source: str):
    if not (interaction.user.guild_permissions.manage_guild if interaction.guild else False):
        await interaction.response.send_message("Serve il permesso **Manage Server**.", ephemeral=True)
        return
    storage.add_muted_source(interaction.channel_id or 0, source)
    await interaction.response.send_message(f"🔇 `{source}` silenziata in questo canale.", ephemeral=True)


@tree.command(name="unmute-source", description="Riattiva una fonte silenziata.")
@app_commands.describe(source="Nome della fonte da riattivare")
@app_commands.autocomplete(source=_source_autocomplete)
async def unmute_source_cmd(interaction: discord.Interaction, source: str):
    if not (interaction.user.guild_permissions.manage_guild if interaction.guild else False):
        await interaction.response.send_message("Serve il permesso **Manage Server**.", ephemeral=True)
        return
    removed = storage.remove_muted_source(interaction.channel_id or 0, source)
    if removed:
        await interaction.response.send_message(f"🔊 `{source}` riattivata.", ephemeral=True)
    else:
        await interaction.response.send_message(f"`{source}` non era silenziata.", ephemeral=True)


@tree.command(name="list-muted", description="Mostra le fonti silenziate in questo canale.")
async def list_muted_cmd(interaction: discord.Interaction):
    muted = storage.list_muted_sources(interaction.channel_id or 0)
    if not muted:
        await interaction.response.send_message("Nessuna fonte silenziata.", ephemeral=True)
        return
    await interaction.response.send_message(
        "Fonti silenziate:\n" + "\n".join(f"• {s}" for s in muted),
        ephemeral=True,
    )


# --- Reaction feedback ---

def _is_feedback_emoji(name: str | None) -> tuple[int, int] | None:
    if name == FEEDBACK_UP:
        return (1, 0)
    if name == FEEDBACK_DOWN:
        return (0, 1)
    return None


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if not ENABLE_REACTION_FEEDBACK:
        return
    if payload.user_id == (client.user.id if client.user else 0):
        return
    delta = _is_feedback_emoji(payload.emoji.name)
    if delta is None:
        return
    source = storage.get_message_source(payload.message_id)
    if not source:
        return
    storage.bump_source_stat(source, delta[0], delta[1])


@client.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if not ENABLE_REACTION_FEEDBACK:
        return
    delta = _is_feedback_emoji(payload.emoji.name)
    if delta is None:
        return
    source = storage.get_message_source(payload.message_id)
    if not source:
        return
    storage.bump_source_stat(source, -delta[0], -delta[1])


@client.event
async def on_ready():
    logger.info("Bot connesso come %s (id=%s)", client.user, client.user.id)
    logger.info(
        "Config: AI_SUMMARY=%s SMART_DEDUP=%s EMBEDDING_DEDUP=%s",
        ENABLE_AI_SUMMARY, ENABLE_SMART_DEDUP, ENABLE_EMBEDDING_DEDUP,
    )
    try:
        channel = client.get_channel(DISCORD_CHANNEL_ID) or await client.fetch_channel(DISCORD_CHANNEL_ID)
        guild = getattr(channel, "guild", None)
        if guild is not None:
            tree.copy_global_to(guild=guild)
            synced = await tree.sync(guild=guild)
            logger.info("Slash commands sincronizzate su %s: %d", guild.name, len(synced))
        else:
            synced = await tree.sync()
            logger.info("Slash commands sincronizzate globalmente: %d", len(synced))
    except Exception as e:
        logger.warning("Sync slash commands fallita: %s", e)
    if not news_cycle.is_running():
        news_cycle.start()


def main() -> None:
    storage.init()
    client.run(DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
