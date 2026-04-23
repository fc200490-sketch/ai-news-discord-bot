"""Discord AI-news bot entry point."""
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, time as dtime, timezone

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
    FETCH_TIMES_UTC,
    NEWS_NOW_COOLDOWN_SECONDS,
    SIMILARITY_THRESHOLD,
    STATE_TTL_DAYS,
)
from dedup import (
    find_semantic_duplicate,
    get_posted_urls,
    load_seen_recent,
    normalize_title,
)
from discord_publisher import FEEDBACK_DOWN, FEEDBACK_UP, ReadMoreView, publish
from feeds import FEEDS_EN, FEEDS_IT
from news_fetcher import fetch_all
from anthropic_scraper import SOURCE_NAME as ANTHROPIC_SOURCE

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
_NEWS_NOW_GC_TTL_S = 3600.0
_cycle_lock = asyncio.Lock()
_commands_synced = False

# --- Runtime metrics (in-memory, reset on restart) ---
_metrics: dict = {
    "started_utc": datetime.now(timezone.utc),
    "cycles": 0,
    "fetched_total": 0,
    "published_total": 0,
    "errors_total": 0,
    "last_cycle_utc": None,
    "last_published": 0,
}

# --- Gateway watchdog state ---
_last_gateway_ok_ts: float = time.monotonic()
_WATCHDOG_MAX_DOWN_S = float(os.getenv("WATCHDOG_MAX_DOWN_SECONDS", "600"))
_WATCHDOG_POLL_S = 60.0


def _gc_news_now(now: float) -> None:
    cutoff = now - _NEWS_NOW_GC_TTL_S
    stale = [k for k, ts in _last_news_now.items() if ts < cutoff]
    for k in stale:
        _last_news_now.pop(k, None)

ALL_SOURCE_NAMES = sorted(
    {n for n, *_ in FEEDS_EN} | {n for n, *_ in FEEDS_IT} | {ANTHROPIC_SOURCE}
)


async def _compute_embeddings(items: list[dict]) -> None:
    if not ENABLE_EMBEDDING_DEDUP or not items:
        return
    coros = [embeddings.embed(it["title"]) for it in items]
    results = await asyncio.gather(*coros, return_exceptions=True)
    ok = 0
    for item, res in zip(items, results):
        if isinstance(res, Exception) or res is None:
            continue
        item["embedding"] = res
        ok += 1
    failed = len(items) - ok
    if failed:
        logger.warning("Embeddings: %d/%d OK, %d failed", ok, len(items), failed)
    else:
        logger.info("Embeddings: %d/%d OK", ok, len(items))


def _prefilter(fresh: list[dict], channel_id: int) -> list[dict]:
    """Cheap filters (URL dedup + muted sources) — run BEFORE expensive Gemini
    embedding calls so we don't spend quota on items we'll throw away."""
    posted_urls = get_posted_urls(window_hours=STATE_TTL_DAYS * 24)
    muted = set(storage.list_muted_sources(channel_id))
    candidates: list[dict] = []
    for item in fresh:
        if item["url"] in posted_urls:
            continue
        if item.get("source") in muted:
            continue
        item["title_norm"] = normalize_title(item["title"])
        candidates.append(item)
    return candidates


def _semantic_group(candidates: list[dict]) -> list[dict]:
    """Semantic dedup against recent history + intra-cycle grouping."""
    if not ENABLE_SMART_DEDUP:
        return candidates

    seen_recent = load_seen_recent(DEDUP_WINDOW_HOURS)
    kept: list[dict] = []
    # Incremental view of kept items, to avoid rebuilding on each candidate.
    kept_view: list[dict] = []
    kept_by_url: dict[str, dict] = {}

    for item in candidates:
        # vs already-posted (cross-cycle): discard, can't retro-edit old messages
        match = find_semantic_duplicate(
            item, seen_recent,
            EMBEDDING_SIMILARITY_THRESHOLD, SIMILARITY_THRESHOLD,
            DEDUP_WINDOW_HOURS,
        )
        if match:
            logger.info("Dropped (already seen): %r ≈ %s", item["title"], match["url"])
            continue

        # vs kept intra-cycle: merge sources instead of discarding
        match = find_semantic_duplicate(
            item, kept_view,
            EMBEDDING_SIMILARITY_THRESHOLD, SIMILARITY_THRESHOLD,
            DEDUP_WINDOW_HOURS,
        )
        if match:
            k = kept_by_url.get(match["url"])
            if k is not None:
                k.setdefault("also_on", [])
                src = item.get("source")
                if src and src not in k["also_on"] and src != k.get("source"):
                    k["also_on"].append(src)
                logger.info(
                    "Merged: %r from %s into %s",
                    item["title"], src, k["url"],
                )
            continue

        kept.append(item)
        kept_by_url[item["url"]] = item
        kept_view.append({
            "url": item["url"],
            "ts": item["published"].isoformat(),
            "title_norm": item["title_norm"],
            "embedding": item.get("embedding"),
        })
    return kept


async def _attach_summaries(items: list[dict]) -> None:
    if not ENABLE_AI_SUMMARY or not items:
        return
    coros = [
        ai_summarizer.summarize(it["title"], it.get("summary", ""))
        for it in items
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)
    for item, res in zip(items, results):
        if isinstance(res, Exception):
            logger.warning("Summarize exception for %s: %s", item.get("url"), res)
            continue
        if res:
            item["summary_ai"] = res


async def run_cycle(channel: discord.abc.Messageable) -> dict:
    """Run one fetch→dedup→publish cycle. Returns stats dict."""
    async with _cycle_lock:
        try:
            items = await fetch_all()
        except Exception as e:
            logger.exception("Fetch error: %s", e)
            _metrics["errors_total"] += 1
            return {"error": str(e), "sent": 0}

        channel_id = getattr(channel, "id", 0)
        candidates = _prefilter(items, channel_id)
        logger.info("%d fetched → %d after URL/mute prefilter", len(items), len(candidates))

        await _compute_embeddings(candidates)

        fresh = _semantic_group(candidates)
        logger.info("%d candidates → %d after dedup/grouping", len(candidates), len(fresh))

        if not fresh:
            return {"fetched": len(items), "sent": 0}

        await _attach_summaries(fresh)

        sent: list[dict] = []
        try:
            sent = await publish(channel, fresh)
        finally:
            try:
                storage.prune()
            except Exception as e:
                logger.debug("Prune failed: %s", e)
        logger.info("Cycle: published %d/%d", len(sent), len(fresh))
        _metrics["cycles"] += 1
        _metrics["fetched_total"] += len(items)
        _metrics["published_total"] += len(sent)
        _metrics["last_cycle_utc"] = datetime.now(timezone.utc)
        _metrics["last_published"] = len(sent)
        return {"fetched": len(items), "kept": len(fresh), "sent": len(sent)}


def _parse_fetch_times(raw: str) -> list[dtime]:
    times: list[dtime] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            hh, mm = chunk.split(":")
            times.append(dtime(int(hh), int(mm), tzinfo=timezone.utc))
        except (ValueError, TypeError):
            logger.warning("FETCH_TIMES_UTC: ignoring invalid value %r", chunk)
    return times


async def _do_news_cycle() -> None:
    channel = client.get_channel(DISCORD_CHANNEL_ID)
    if channel is None:
        try:
            channel = await client.fetch_channel(DISCORD_CHANNEL_ID)
        except Exception as e:
            logger.error("Channel unreachable: %s", e)
            return
    if channel is None:
        logger.error("Channel %s not found", DISCORD_CHANNEL_ID)
        return
    await run_cycle(channel)


_fixed_times = _parse_fetch_times(FETCH_TIMES_UTC)
if _fixed_times:
    logger.info("Scheduler wall-clock UTC: %s", [t.isoformat() for t in _fixed_times])  # noqa: E501
    news_cycle = tasks.loop(time=_fixed_times)(_do_news_cycle)
else:
    if FETCH_TIMES_UTC.strip():
        logger.warning(
            "FETCH_TIMES_UTC=%r contains no valid HH:MM values, "
            "falling back to %d-hour interval.", FETCH_TIMES_UTC, FETCH_INTERVAL_HOURS,
        )
    news_cycle = tasks.loop(hours=FETCH_INTERVAL_HOURS)(_do_news_cycle)


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
    _gc_news_now(now)
    last = _last_news_now.get(interaction.channel_id or 0, 0.0)
    remaining = NEWS_NOW_COOLDOWN_SECONDS - (now - last)
    if remaining > 0:
        await interaction.response.send_message(
            f"Cooldown attivo: riprova tra {int(remaining)}s.", ephemeral=True,
        )
        return
    if interaction.channel is None:
        await interaction.response.send_message(
            "Canale non disponibile.", ephemeral=True,
        )
        return
    _last_news_now[interaction.channel_id or 0] = now
    await interaction.response.defer(ephemeral=True, thinking=True)
    stats = await run_cycle(interaction.channel)
    summary = (
        f"Fatto. Fetched: {stats.get('fetched', 0)} · "
        f"Da pubblicare: {stats.get('kept', 0)} · Pubblicate: {stats.get('sent', 0)}"
    )
    # Interaction token expires after ~15 min. If the cycle took longer, the
    # followup fails — fall back to a regular channel message so the admin
    # still sees the outcome.
    try:
        await interaction.followup.send(summary, ephemeral=True)
    except discord.DiscordException as e:
        logger.warning("Followup /news-now expired (%s); sending to channel.", e)
        try:
            await interaction.channel.send(f"`/news-now` → {summary}")
        except discord.DiscordException:
            pass


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


def _format_runtime_block() -> str:
    started = _metrics["started_utc"]
    uptime = datetime.now(timezone.utc) - started
    hours = int(uptime.total_seconds() // 3600)
    mins = int((uptime.total_seconds() % 3600) // 60)
    last = _metrics["last_cycle_utc"]
    last_str = last.strftime("%d/%m %H:%M UTC") if last else "mai"
    avg = (
        _metrics["published_total"] / _metrics["cycles"]
        if _metrics["cycles"] else 0.0
    )
    return (
        f"**Runtime**\n"
        f"• Uptime: {hours}h{mins:02d}m\n"
        f"• Cicli eseguiti: {_metrics['cycles']}\n"
        f"• Notizie pubblicate: {_metrics['published_total']} "
        f"(media {avg:.1f}/ciclo)\n"
        f"• Errori di fetch: {_metrics['errors_total']}\n"
        f"• Ultimo ciclo: {last_str} ({_metrics['last_published']} pubblicate)"
    )


@tree.command(name="stats", description="Statistiche runtime + 👍/👎 per fonte.")
async def stats_cmd(interaction: discord.Interaction):
    runtime_block = _format_runtime_block()
    stats = storage.get_source_stats()
    if stats:
        ranked = sorted(
            stats.items(),
            key=lambda kv: (kv[1]["up"] - kv[1]["down"], kv[1]["up"]),
            reverse=True,
        )
        feedback_lines = [
            f"• **{src}** — 👍 {v['up']} · 👎 {v['down']}  (net {v['up'] - v['down']:+d})"
            for src, v in ranked[:20]
        ]
        feedback_block = "**Feedback per fonte**\n" + "\n".join(feedback_lines)
    else:
        feedback_block = "**Feedback per fonte**\nNessun feedback registrato."
    await interaction.response.send_message(
        runtime_block + "\n\n" + feedback_block, ephemeral=True,
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


_view_registered = False
_watchdog_started = False


@client.event
async def on_connect():
    global _last_gateway_ok_ts
    _last_gateway_ok_ts = time.monotonic()


@client.event
async def on_resumed():
    global _last_gateway_ok_ts
    _last_gateway_ok_ts = time.monotonic()


async def _gateway_watchdog() -> None:
    """Exit the process if the gateway stays disconnected beyond a grace window.
    Fly restarts the VM, which is faster than waiting for a stuck reconnect loop."""
    while True:
        await asyncio.sleep(_WATCHDOG_POLL_S)
        if client.is_closed():
            down = time.monotonic() - _last_gateway_ok_ts
            if down > _WATCHDOG_MAX_DOWN_S:
                logger.error("Watchdog: gateway down for %.0fs > %.0fs, exiting",
                             down, _WATCHDOG_MAX_DOWN_S)
                sys.exit(1)
        else:
            globals()["_last_gateway_ok_ts"] = time.monotonic()


@client.event
async def on_ready():
    global _commands_synced, _view_registered, _watchdog_started
    logger.info("Bot connected as %s (id=%s)", client.user, client.user.id)
    if not _view_registered:
        client.add_view(ReadMoreView())
        _view_registered = True
    if not _watchdog_started:
        client.loop.create_task(_gateway_watchdog())
        _watchdog_started = True
    logger.info(
        "Config: AI_SUMMARY=%s SMART_DEDUP=%s EMBEDDING_DEDUP=%s",
        ENABLE_AI_SUMMARY, ENABLE_SMART_DEDUP, ENABLE_EMBEDDING_DEDUP,
    )
    if not _commands_synced:
        try:
            synced = await tree.sync()
            logger.info("Slash commands synced globally: %d", len(synced))
            _commands_synced = True
        except Exception as e:
            logger.warning("Sync slash commands failed: %s", e)
    if not news_cycle.is_running():
        news_cycle.start()


def main() -> None:
    storage.init()
    client.run(DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
