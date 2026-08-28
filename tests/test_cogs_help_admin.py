"""-help and the /admin slash commands."""

from __future__ import annotations

import asyncio

import pytest

from paradox_bot import feedback
from paradox_bot.cogs.admin import AdminGroup, _format_uptime
from paradox_bot.cogs.help import HelpCog
from paradox_bot.config import settings
from paradox_bot.games import GAMES
from tests.conftest import FakeContext, FakeInteraction, insert_page

# --- -help -------------------------------------------------------------------


def test_help_lists_every_game(ctx: FakeContext) -> None:
    cog = HelpCog(bot=object())
    asyncio.run(cog.help_command.callback(cog, ctx))
    description = ctx.embeds[0].description
    for key, game in GAMES.items():
        assert f"{settings.bot_prefix}{key}" in description
        assert game.name in description


def test_help_lists_the_non_game_commands(ctx: FakeContext) -> None:
    cog = HelpCog(bot=object())
    asyncio.run(cog.help_command.callback(cog, ctx))
    description = ctx.embeds[0].description
    for command in ("tools", "random", "trending"):
        assert f"{settings.bot_prefix}{command}" in description


def test_help_follows_a_custom_prefix(ctx: FakeContext, monkeypatch) -> None:
    monkeypatch.setattr(settings, "bot_prefix", "!")
    cog = HelpCog(bot=object())
    asyncio.run(cog.help_command.callback(cog, ctx))
    assert "!eu4" in ctx.embeds[0].description


# --- /admin ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0 хв"),
        (90, "1 хв"),
        (3600, "1 год 0 хв"),
        (3661, "1 год 1 хв"),
        (86400, "1 дн 0 год"),
        (90061, "1 дн 1 год"),
    ],
)
def test_format_uptime(seconds: int, expected: str) -> None:
    assert _format_uptime(seconds) == expected


class FakeBot:
    def __init__(self) -> None:
        from datetime import UTC, datetime

        self.started_at = datetime.now(UTC)
        self.guilds = [object(), object()]
        self.latency = 0.042


def test_status_reports_guilds_latency_and_databases(
    interaction: FakeInteraction, game_db
) -> None:
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")
    group = AdminGroup(bot=FakeBot())

    asyncio.run(group.status.callback(group, interaction))

    sent = interaction.response.sent[0]
    assert sent["ephemeral"] is True
    description = sent["embed"].description
    assert "Гільдій: 2" in description
    assert "Затримка: 42 мс" in description
    assert "Test Game**: 1 стор." in description


def test_status_flags_a_missing_database(interaction: FakeInteraction, monkeypatch, tmp_path):
    # Point at an empty directory so every configured game has no file.
    monkeypatch.setattr(settings, "db_dir", tmp_path)
    group = AdminGroup(bot=FakeBot())

    asyncio.run(group.status.callback(group, interaction))

    assert "БД відсутня" in interaction.response.sent[0]["embed"].description


async def test_feedback_reports_when_empty(interaction: FakeInteraction, db):
    group = AdminGroup(bot=FakeBot())

    await group.feedback_cmd.callback(group, interaction)

    sent = interaction.response.sent[0]
    assert "Ще немає жодного голосу" in sent["content"]
    assert sent["ephemeral"] is True


async def test_feedback_lists_votes_newest_first(interaction: FakeInteraction, db):
    await feedback.record_feedback("msg-1", "1", "eu4", "absolutism", "up", "Absolutism", "u")
    await feedback.record_feedback("msg-2", "2", "hoi4", "germany", "down", None, None)
    group = AdminGroup(bot=FakeBot())

    await group.feedback_cmd.callback(group, interaction)

    description = interaction.response.sent[0]["embed"].description
    lines = description.split("\n")
    assert lines[0].startswith("❌")
    assert "germany" in lines[0]
    # A vote on an empty result still renders, with a placeholder title.
    assert "(нічого не знайдено)" in lines[0]
    assert lines[1].startswith("✅")
    assert "Absolutism" in lines[1]


async def test_feedback_respects_the_limit(interaction: FakeInteraction, db):
    for i in range(5):
        await feedback.record_feedback(f"msg-{i}", "1", "eu4", f"query {i}", "up", "T", "u")
    group = AdminGroup(bot=FakeBot())

    await group.feedback_cmd.callback(group, interaction, limit=2)

    description = interaction.response.sent[0]["embed"].description
    assert len(description.split("\n")) == 2
    assert "Останні 2 голосів" in interaction.response.sent[0]["embed"].title
