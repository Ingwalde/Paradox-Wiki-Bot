"""The search use-case: query -> reply -> record.

Sits between the Discord layer (bot.py, cogs/) and the data layer (search,
stats, feedback). Kept out of bot.py so the bot class is only wiring: intents,
cogs, events.
"""

from __future__ import annotations

import logging
import time

import discord
from discord import ui
from discord.ext import commands

from paradox_bot import metrics, search, search_context, stats
from paradox_bot.config import settings
from paradox_bot.feedback import FEEDBACK_EMOJIS
from paradox_bot.games import GAMES
from paradox_bot.storage import StorageError
from paradox_bot.ui.views import LinksView, PaginatedResultsView, build_links_field

logger = logging.getLogger(__name__)

async def perform_search(
    bot: commands.Bot, ctx: commands.Context, game_key: str, query: str
) -> None:
    """Search one game's wiki and reply with an embed plus link buttons."""
    game = GAMES[game_key]

    if len(query) > settings.max_query_length:
        await ctx.send(f"❌ Запит задовгий (максимум {settings.max_query_length} символів).")
        return

    started = time.perf_counter()
    try:
        pages = await search.search_pages(game_key, query, limit=settings.search_max_results)
    except StorageError:
        metrics.DB_ERRORS.labels(operation="search").inc()
        logger.exception("Database search failed for %s: %r", game_key, query)
        await ctx.send("⚠️ Не вдалося виконати пошук. Спробуйте пізніше.")
        return
    metrics.SEARCH_DURATION.observe(time.perf_counter() - started)
    metrics.SEARCHES.labels(game=game_key).inc()
    if not pages:
        metrics.EMPTY_RESULTS.labels(game=game_key).inc()

    try:
        await stats.record_search(game_key, query)
    except StorageError:
        metrics.DB_ERRORS.labels(operation="stats").inc()
        logger.exception("Could not record search stats for %s: %r", game_key, query)

    view: ui.View | None = None
    if pages:
        results_view = PaginatedResultsView(pages, game, author_id=ctx.author.id)
        embed = results_view.build_embed()
        view = results_view
    else:
        embed = discord.Embed(
            title=f"За запитом '{query}' нічого не знайдено",
            description="Спробуйте інший запит або перевірте написання.",
            color=game.color,
        )
        if game.logo:
            embed.set_thumbnail(url=game.logo)
        try:
            suggestions = await search.suggest_similar(game_key, query)
        except StorageError:
            metrics.DB_ERRORS.labels(operation="suggest").inc()
            logger.exception("Fuzzy suggestion lookup failed for %s: %r", game_key, query)
            suggestions = []
        if suggestions:
            links_text = build_links_field(suggestions)
            if links_text:
                embed.add_field(
                    name="🔎 Можливо ви мали на увазі", value=links_text, inline=False
                )
            view = LinksView(suggestions)
        embed.set_footer(text=f"{game.name} Wiki")

    msg = await ctx.send(embed=embed, view=view) if view else await ctx.send(embed=embed)
    if isinstance(view, PaginatedResultsView):
        view.message = msg
    search_context.remember(
        msg.id,
        game_key=game_key,
        query=query,
        top_title=pages[0]["title"] if pages else None,
        top_url=pages[0]["url"] if pages else None,
    )
    for emoji in FEEDBACK_EMOJIS:
        try:
            await msg.add_reaction(emoji)
        except discord.HTTPException:
            logger.warning("Could not add reaction %s", emoji, exc_info=True)

    await log_request(
        bot=bot,
        ctx=ctx,
        game_key=game_key,
        query=query,
        found=bool(pages),
        result_count=len(pages),
        has_image=bool(pages and pages[0].get("image_url")),
    )


async def log_request(
    bot: commands.Bot,
    ctx: commands.Context,
    game_key: str,
    query: str,
    found: bool,
    result_count: int,
    has_image: bool,
) -> None:
    """Mirror a search request into the log channel. Never fails the command."""
    logger.info(
        "search game=%s user=%s query=%r results=%d", game_key, ctx.author.id, query, result_count
    )
    if settings.log_channel_id is None:
        return

    channel = bot.get_channel(settings.log_channel_id)
    if channel is None:
        logger.warning("Log channel %s not found or not cached", settings.log_channel_id)
        return
    if not isinstance(channel, discord.abc.Messageable):
        logger.error(
            "LOG_CHANNEL_ID %s is a %s, which can't receive messages",
            settings.log_channel_id,
            type(channel).__name__,
        )
        return

    game = GAMES[game_key]
    embed = discord.Embed(title="📄 Paradox Wiki Запит", color=game.color)
    embed.add_field(name="**User**", value=f"<@{ctx.author.id}>", inline=False)
    embed.add_field(
        name="**Request**", value=f"`{settings.bot_prefix}{game_key} {query}`", inline=False
    )
    embed.add_field(
        name="**Result**",
        value=(
            f"Знайдено: {'так' if found else 'ні'}\n"
            f"Кількість результатів: {result_count}\n"
            f"Картинка: {'так' if has_image else 'ні'}"
        ),
        inline=False,
    )
    try:
        await channel.send(embed=embed)
    except discord.DiscordException:
        logger.exception("Failed to write to log channel %s", settings.log_channel_id)
