"""-random, -trending, and the daily-fact auto-post."""

from __future__ import annotations

import logging
import random
from datetime import UTC, time

import discord
from discord.ext import commands, tasks

from paradox_bot import search, stats
from paradox_bot.config import settings
from paradox_bot.games import GAMES
from paradox_bot.storage import StorageError

logger = logging.getLogger(__name__)

DAILY_FACT_TIME = time(hour=12, tzinfo=UTC)


def _unknown_game_message(game_key: str) -> str:
    available = ", ".join(sorted(GAMES))
    return f"❌ Невідома гра `{game_key}`. Доступні: {available}"


def _build_page_embed(page: dict, game_key: str, footer_prefix: str) -> discord.Embed:
    game = GAMES[game_key]
    embed = discord.Embed(title=page["title"], url=page["url"], color=game.color)
    embed.set_thumbnail(url=game.logo)
    if page.get("image_url"):
        embed.set_image(url=page["image_url"])
    embed.set_footer(text=f"{footer_prefix} · {game.name} Wiki")
    return embed


class ExtrasCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        if settings.daily_fact_channel_id:
            self.daily_fact.start()

    async def cog_unload(self) -> None:
        self.daily_fact.cancel()

    @commands.command(name="random", help="Випадкова стаття з вікі")
    @commands.cooldown(
        settings.search_cooldown_uses,
        settings.search_cooldown_seconds,
        commands.BucketType.user,
    )
    async def random_command(self, ctx: commands.Context, game_key: str) -> None:
        game_key = game_key.lower()
        if game_key not in GAMES:
            await ctx.send(_unknown_game_message(game_key))
            return

        try:
            page = await search.random_page(game_key)
        except StorageError:
            logger.exception("Random page lookup failed for %s", game_key)
            await ctx.send("⚠️ Не вдалося отримати випадкову статтю.")
            return

        if page is None:
            await ctx.send("⚠️ У цій грі поки немає даних.")
            return

        await ctx.send(embed=_build_page_embed(page, game_key, "🎲 Випадкова стаття"))

    @commands.command(name="trending", help="Топ запитів за останній тиждень")
    @commands.cooldown(
        settings.search_cooldown_uses,
        settings.search_cooldown_seconds,
        commands.BucketType.user,
    )
    async def trending_command(self, ctx: commands.Context, game_key: str) -> None:
        game_key = game_key.lower()
        if game_key not in GAMES:
            await ctx.send(_unknown_game_message(game_key))
            return

        rows = await stats.trending(game_key)
        if not rows:
            await ctx.send("Ще немає даних для цієї гри.")
            return

        game = GAMES[game_key]
        lines = [f"{i}. **{row['query']}** ({row['count']})" for i, row in enumerate(rows, 1)]
        embed = discord.Embed(
            title=f"🔥 Топ запитів · {game.name}",
            description="\n".join(lines),
            color=game.color,
        )
        await ctx.send(embed=embed)

    @tasks.loop(time=DAILY_FACT_TIME)
    async def daily_fact(self) -> None:
        if settings.daily_fact_channel_id is None:
            return
        channel = self.bot.get_channel(settings.daily_fact_channel_id)
        if channel is None or not isinstance(channel, discord.abc.Messageable):
            logger.warning(
                "DAILY_FACT_CHANNEL_ID %s not found or can't receive messages",
                settings.daily_fact_channel_id,
            )
            return

        game_key = random.choice(list(GAMES))
        try:
            page = await search.random_page(game_key)
        except StorageError:
            logger.exception("Daily fact lookup failed for %s", game_key)
            return
        if page is None:
            return

        await channel.send(embed=_build_page_embed(page, game_key, "📅 Факт дня"))

    @daily_fact.before_loop
    async def before_daily_fact(self) -> None:
        await self.bot.wait_until_ready()
