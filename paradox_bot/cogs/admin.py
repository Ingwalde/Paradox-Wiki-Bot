"""Admin-only slash commands: /admin status, /admin feedback.

Gated by Discord's own default_permissions(administrator=True) on the group
-- no separate owner-id list to maintain.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

import discord
from discord import app_commands

from paradox_bot import feedback, search
from paradox_bot.games import GAMES


class BotStatus(Protocol):
    """The three things /admin status reads off the bot.

    A Protocol rather than `ParadoxBot`: importing the concrete class here made
    admin.py depend on bot.py while bot.py registers this cog, and the cycle was
    only survivable because bot.py imported its cogs inside setup_hook(). Typing
    against what is actually used breaks the loop, and lets the tests pass a
    plain stub instead of constructing a real bot.
    """

    started_at: datetime

    # Properties, not plain attributes: discord.Client exposes both as
    # read-only, and a Protocol declaring them settable would reject the real
    # bot.
    @property
    def guilds(self) -> Sequence[object]: ...

    @property
    def latency(self) -> float: ...


def _format_uptime(delta_seconds: float) -> str:
    total_minutes = int(delta_seconds // 60)
    hours, minutes = divmod(total_minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days} дн {hours} год"
    if hours:
        return f"{hours} год {minutes} хв"
    return f"{minutes} хв"


class AdminGroup(app_commands.Group):
    def __init__(self, bot: BotStatus) -> None:
        super().__init__(
            name="admin",
            description="Адмін-команди",
            default_permissions=discord.Permissions(administrator=True),
        )
        self.bot = bot

    @app_commands.command(name="status", description="Статус і здоров'я бота")
    async def status(self, interaction: discord.Interaction) -> None:
        uptime = (datetime.now(UTC) - self.bot.started_at).total_seconds()
        lines = [
            f"Гільдій: {len(self.bot.guilds)}",
            f"Затримка: {self.bot.latency * 1000:.0f} мс",
            f"Аптайм: {_format_uptime(uptime)}",
            "",
        ]
        for key, game in GAMES.items():
            stats = await asyncio.to_thread(search.db_stats, key)
            if stats is None:
                lines.append(f"**{game.name}**: БД відсутня")
                continue
            modified = datetime.fromtimestamp(stats["modified"], tz=UTC)
            lines.append(
                f"**{game.name}**: {stats['pages']} стор., {stats['redirects']} редиректів "
                f"(оновлено {modified:%Y-%m-%d})"
            )
        embed = discord.Embed(
            title="📊 Статус бота", description="\n".join(lines), color=0x2B4570
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="feedback", description="Останні ✅/❌ голоси")
    @app_commands.describe(limit="Скільки останніх голосів показати (за замовчуванням 10)")
    async def feedback_cmd(self, interaction: discord.Interaction, limit: int = 10) -> None:
        rows = await asyncio.to_thread(feedback.recent_feedback, limit)
        if not rows:
            await interaction.response.send_message("Ще немає жодного голосу.", ephemeral=True)
            return

        lines = []
        for row in rows:
            emoji = "✅" if row["vote"] == "up" else "❌"
            title = row["top_title"] or "(нічого не знайдено)"
            lines.append(f"{emoji} `{row['game_key']}` **{row['query']}** → {title}")

        embed = discord.Embed(
            title=f"🗳️ Останні {len(rows)} голосів",
            description="\n".join(lines),
            color=0x2B4570,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
