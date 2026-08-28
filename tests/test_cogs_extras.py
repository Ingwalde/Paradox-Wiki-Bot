"""-random, -trending and the daily-fact loop.

Commands are invoked through `.callback(cog, ctx, ...)` so the cooldown wrapper
is bypassed -- rate limiting is asserted separately in test_bot_limits.py, and
going through it here would make every test after the fourth fail on cooldown.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from paradox_bot import stats
from paradox_bot.cogs.extras import ExtrasCog, _build_page_embed, _unknown_game_message
from paradox_bot.config import settings
from paradox_bot.games import GAMES
from tests.conftest import FakeContext, FakeSendable, insert_page


@pytest.fixture()
def cog(monkeypatch: pytest.MonkeyPatch) -> ExtrasCog:
    # Force the channel off before constructing: ExtrasCog starts the
    # daily_fact task loop when one is configured, which needs a running event
    # loop. A developer with DAILY_FACT_CHANNEL_ID in their .env would
    # otherwise get errors CI never sees. Tests that exercise the loop set the
    # channel themselves and call daily_fact() directly.
    monkeypatch.setattr(settings, "daily_fact_channel_id", None)
    return ExtrasCog(bot=object())


def test_unknown_game_message_lists_available_games() -> None:
    message = _unknown_game_message("nope")
    assert "nope" in message
    for key in GAMES:
        assert key in message


def test_build_page_embed_sets_title_url_and_footer() -> None:
    page = {"title": "Absolutism", "url": "https://wiki/Absolutism", "image_url": ""}
    embed = _build_page_embed(page, "eu4", "🎲 Випадкова стаття")
    assert embed.title == "Absolutism"
    assert embed.url == "https://wiki/Absolutism"
    assert embed.footer.text == "🎲 Випадкова стаття · Europa Universalis 4 Wiki"
    assert embed.image.url is None


def test_build_page_embed_sets_image_when_present() -> None:
    page = {"title": "A", "url": "u", "image_url": "https://wiki/img.png"}
    embed = _build_page_embed(page, "eu4", "x")
    assert embed.image.url == "https://wiki/img.png"


def test_random_rejects_unknown_game(cog: ExtrasCog, ctx: FakeContext) -> None:
    asyncio.run(cog.random_command.callback(cog, ctx, "notagame"))
    assert "Невідома гра" in ctx.texts[0]
    assert not ctx.embeds


def test_random_is_case_insensitive_about_the_game(
    cog: ExtrasCog, ctx: FakeContext, game_db
) -> None:
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")
    asyncio.run(cog.random_command.callback(cog, ctx, "TEST"))
    assert ctx.embeds[0].title == "Absolutism"


def test_random_sends_a_page_embed(cog: ExtrasCog, ctx: FakeContext, game_db) -> None:
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")
    asyncio.run(cog.random_command.callback(cog, ctx, "test"))
    embed = ctx.embeds[0]
    assert embed.title == "Absolutism"
    assert "Випадкова стаття" in embed.footer.text


def test_random_reports_empty_database(cog: ExtrasCog, ctx: FakeContext, game_db) -> None:
    asyncio.run(cog.random_command.callback(cog, ctx, "test"))
    assert "немає даних" in ctx.texts[0]


def test_random_survives_a_database_error(
    cog: ExtrasCog, ctx: FakeContext, game_db, monkeypatch
) -> None:
    async def boom(_game_key: str) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr("paradox_bot.cogs.extras.random_page_async", boom)
    asyncio.run(cog.random_command.callback(cog, ctx, "test"))
    assert "Не вдалося" in ctx.texts[0]


def test_trending_rejects_unknown_game(cog: ExtrasCog, ctx: FakeContext) -> None:
    asyncio.run(cog.trending_command.callback(cog, ctx, "notagame"))
    assert "Невідома гра" in ctx.texts[0]


async def test_trending_reports_no_data(cog: ExtrasCog, ctx: FakeContext, db) -> None:
    await cog.trending_command.callback(cog, ctx, "eu4")
    assert "Ще немає даних" in ctx.texts[0]


async def test_trending_lists_queries_by_frequency(cog: ExtrasCog, ctx: FakeContext, db) -> None:
    await stats.record_search("eu4", "absolutism")
    await stats.record_search("eu4", "absolutism")
    await stats.record_search("eu4", "prussia")

    await cog.trending_command.callback(cog, ctx, "eu4")

    description = ctx.embeds[0].description
    assert "1. **absolutism** (2)" in description
    assert "2. **prussia** (1)" in description


class _FakeBot:
    """Bot stand-in for the daily-fact loop: only get_channel is reached."""

    def __init__(self, channel: object | None) -> None:
        self._channel = channel

    def get_channel(self, _channel_id: int) -> object | None:
        return self._channel


def test_daily_fact_posts_a_page(cog: ExtrasCog, game_db, monkeypatch) -> None:
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")
    channel = FakeSendable()
    monkeypatch.setattr(settings, "daily_fact_channel_id", 123)
    monkeypatch.setattr(cog, "bot", _FakeBot(channel))
    # Every game but the temp one has a real database; pin it to the temp game
    # so the assertion does not depend on which game random.choice lands on.
    monkeypatch.setattr("paradox_bot.cogs.extras.random.choice", lambda _seq: "test")

    asyncio.run(cog.daily_fact())

    assert channel.embeds[0].title == "Absolutism"
    assert "Факт дня" in channel.embeds[0].footer.text


def test_daily_fact_does_nothing_when_unconfigured(cog: ExtrasCog, monkeypatch) -> None:
    channel = FakeSendable()
    monkeypatch.setattr(settings, "daily_fact_channel_id", None)
    monkeypatch.setattr(cog, "bot", _FakeBot(channel))
    asyncio.run(cog.daily_fact())
    assert channel.sent == []


def test_daily_fact_skips_a_missing_channel(cog: ExtrasCog, monkeypatch) -> None:
    monkeypatch.setattr(settings, "daily_fact_channel_id", 123)
    monkeypatch.setattr(cog, "bot", _FakeBot(None))
    asyncio.run(cog.daily_fact())  # must not raise


def test_daily_fact_skips_a_non_messageable_channel(cog: ExtrasCog, monkeypatch) -> None:
    monkeypatch.setattr(settings, "daily_fact_channel_id", 123)
    # A category or forum channel has no .send(); posting to one would raise.
    monkeypatch.setattr(cog, "bot", _FakeBot(object()))
    asyncio.run(cog.daily_fact())  # must not raise


def test_daily_fact_survives_a_database_error(cog: ExtrasCog, monkeypatch) -> None:
    async def boom(_game_key: str) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    channel = FakeSendable()
    monkeypatch.setattr(settings, "daily_fact_channel_id", 123)
    monkeypatch.setattr(cog, "bot", _FakeBot(channel))
    monkeypatch.setattr("paradox_bot.cogs.extras.random_page_async", boom)
    asyncio.run(cog.daily_fact())
    assert channel.sent == []
