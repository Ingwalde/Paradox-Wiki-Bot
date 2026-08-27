"""The ParadoxBot class: intents, cog wiring, and event handlers.

Deliberately thin. Presentation lives in ui/, the search use-case in
search_flow.py, persistence in storage-backed modules. This file should only
ever grow a new event handler or a new cog registration.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime

import discord
from discord.ext import commands

from paradox_bot import search_context
from paradox_bot.cogs.admin import AdminGroup
from paradox_bot.cogs.extras import ExtrasCog
from paradox_bot.cogs.help import HelpCog
from paradox_bot.cogs.tools import ToolsCog
from paradox_bot.config import settings
from paradox_bot.feedback import FEEDBACK_EMOJIS, record_feedback
from paradox_bot.games import GAMES
from paradox_bot.search_flow import perform_search
from paradox_bot.web import KeepAliveServer

logger = logging.getLogger(__name__)


class ParadoxBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=settings.bot_prefix,
            intents=intents,
            help_command=None,
            # Without this, -EU4 raises CommandNotFound and is swallowed
            # silently, so anything but lowercase looks like a dead bot.
            case_insensitive=True,
        )
        self.started_at = datetime.now(UTC)
        self.keep_alive = KeepAliveServer()
        self._register_game_commands()

    async def close(self) -> None:
        """Stop the health endpoint before the gateway connection goes away.

        Ordering matters under `docker stop`: the health endpoint must stop
        answering while we are shutting down, not keep reporting healthy for a
        bot that is on its way out.
        """
        await self.keep_alive.stop()
        await super().close()

    def _register_game_commands(self) -> None:
        """Register one prefix command per game.

        Data-driven (one entry per GAMES key), so it stays a plain loop
        instead of a Cog: forcing a dynamic command set into a Cog's
        decorator-based style would add friction for no benefit.

        The game key is bound by the enclosing function scope, not by a
        default argument -- a default would make it an optional positional
        the user could override from chat, which previously let arbitrary
        text reach db_path().
        """
        for key, game in GAMES.items():

            def make_command(game_key: str):
                @commands.cooldown(
                    settings.search_cooldown_uses,
                    settings.search_cooldown_seconds,
                    commands.BucketType.user,
                )
                async def game_command(ctx: commands.Context, *, query: str) -> None:
                    await perform_search(self, ctx, game_key, query)

                return game_command

            self.command(name=key, help=f"Пошук у вікі {game.name}")(make_command(key))

    async def setup_hook(self) -> None:
        await self.add_cog(ToolsCog(self))
        await self.add_cog(HelpCog(self))
        await self.add_cog(ExtrasCog(self))
        self.tree.add_command(AdminGroup(self))

        await self.keep_alive.start()

        if settings.dev_guild_id:
            guild = discord.Object(id=settings.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Synced admin commands to dev guild %s", settings.dev_guild_id)
        else:
            await self.tree.sync()
            logger.info("Synced admin commands globally (can take up to an hour to appear)")

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        """Turn framework errors into user-facing messages instead of stderr noise."""
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❓ Вкажіть запит: `{settings.bot_prefix}{ctx.invoked_with} <запит>`")
            return
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Зачекайте {error.retry_after:.0f} с перед наступним запитом.")
            return
        if isinstance(error, commands.MaxConcurrencyReached):
            await ctx.send("⏳ Попереднє завантаження ще триває. Завершіть його спершу.")
            return

        original = getattr(error, "original", error)
        logger.error("Command %s failed", ctx.command, exc_info=original)
        await ctx.send("⚠️ Сталася помилка під час виконання команди.")

    async def on_ready(self) -> None:
        logger.info("Logged in as %s", self.user)

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """Record ✅/❌ feedback on a search-result message.

        Uses the raw event, not on_reaction_add, so feedback still registers
        on messages the message cache has evicted.
        """
        if self.user is not None and payload.user_id == self.user.id:
            return
        vote = FEEDBACK_EMOJIS.get(str(payload.emoji))
        if vote is None:
            return
        context = search_context.get(payload.message_id)
        if context is None:
            return

        logger.info(
            "feedback vote=%s user=%s game=%s query=%r top_title=%r top_url=%r",
            vote,
            payload.user_id,
            context["game_key"],
            context["query"],
            context["top_title"],
            context["top_url"],
        )
        try:
            await asyncio.to_thread(
                record_feedback,
                str(payload.message_id),
                str(payload.user_id),
                context["game_key"],
                context["query"],
                vote,
                context["top_title"],
                context["top_url"],
            )
        except sqlite3.Error:
            logger.exception("Could not record feedback for message %s", payload.message_id)

