"""Tests for the search use-case: query -> reply -> record.

perform_search is what a user actually experiences, and every branch of it is
reachable without a gateway connection: the Discord surface it touches is
ctx.send(), message.add_reaction() and bot.get_channel(), all of which the
fakes in conftest.py already stand in for.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import discord
import pytest

from conftest import FakeContext, FakeSendable, insert_page
from paradox_bot import search_context, search_flow, stats
from paradox_bot.config import settings
from paradox_bot.feedback import FEEDBACK_EMOJIS
from paradox_bot.ui.views import LinksView, PaginatedResultsView


class _FakeHTTPResponse:
    """The two attributes discord.HTTPException formats its message from."""

    status = 403
    reason = "Forbidden"


def http_error(message: str) -> discord.HTTPException:
    return discord.HTTPException(_FakeHTTPResponse(), message)


class FakeBot:
    """Only get_channel() is reached from the search flow."""

    def __init__(self, channel: object = None) -> None:
        self._channel = channel
        self.asked_for: list[int] = []

    def get_channel(self, channel_id: int) -> object:
        self.asked_for.append(channel_id)
        return self._channel


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep search context and the stats database out of each other's way."""
    monkeypatch.setattr(settings, "stats_db_path", tmp_path / "stats.db")
    monkeypatch.setattr(settings, "log_channel_id", None)
    search_context.clear()


def run_search(bot: object, ctx: FakeContext, query: str, game_key: str = "test") -> None:
    asyncio.run(search_flow.perform_search(bot, ctx, game_key, query))


# --- the happy path ----------------------------------------------------------


def test_found_results_render_an_embed_with_the_top_hit(game_db, ctx: FakeContext) -> None:
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")

    run_search(FakeBot(), ctx, "absolutism")

    embed = ctx.embeds[0]
    assert embed.title == "Absolutism"
    assert embed.url == "https://wiki/Absolutism"


def test_found_results_attach_a_paginated_view(game_db, ctx: FakeContext) -> None:
    for i in range(12):
        insert_page(game_db, f"Trade node {i}", f"https://wiki/Trade_node_{i}")

    run_search(FakeBot(), ctx, "trade node")

    view = ctx.sent[0].view
    assert isinstance(view, PaginatedResultsView)
    assert view.total_pages > 1
    # on_timeout needs the message to be able to disable the buttons.
    assert view.message is ctx.sent[0]


def test_the_searcher_owns_the_pagination(game_db, ctx: FakeContext) -> None:
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")

    run_search(FakeBot(), ctx, "absolutism")

    assert ctx.sent[0].view.author_id == ctx.author.id


def test_feedback_reactions_are_added(game_db, ctx: FakeContext) -> None:
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")

    run_search(FakeBot(), ctx, "absolutism")

    assert ctx.sent[0].reactions == list(FEEDBACK_EMOJIS)


def test_the_search_is_remembered_for_the_reaction_handler(game_db, ctx: FakeContext) -> None:
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism", "https://img/a.png")

    run_search(FakeBot(), ctx, "absolutism")

    context = search_context.get(ctx.sent[0].id)
    assert context == {
        "game_key": "test",
        "query": "absolutism",
        "top_title": "Absolutism",
        "top_url": "https://wiki/Absolutism",
    }


def test_the_search_is_recorded_in_the_stats_database(game_db, ctx: FakeContext) -> None:
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")

    run_search(FakeBot(), ctx, "absolutism")

    assert stats.trending("test") == [{"query": "absolutism", "count": 1}]


# --- nothing found -----------------------------------------------------------


def test_no_results_says_so_and_offers_fuzzy_suggestions(game_db, ctx: FakeContext) -> None:
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")

    run_search(FakeBot(), ctx, "absolutisn")

    embed = ctx.embeds[0]
    assert "нічого не знайдено" in embed.title
    assert embed.fields[0].name == "🔎 Можливо ви мали на увазі"
    assert "Absolutism" in embed.fields[0].value
    assert isinstance(ctx.sent[0].view, LinksView)


def test_no_results_and_no_suggestions_sends_a_bare_embed(game_db, ctx: FakeContext) -> None:
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")

    run_search(FakeBot(), ctx, "zzzzzzzzzz")

    embed = ctx.embeds[0]
    assert "нічого не знайдено" in embed.title
    assert embed.fields == []
    assert ctx.sent[0].view is None


def test_no_results_still_records_the_search_and_its_context(game_db, ctx: FakeContext) -> None:
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")

    run_search(FakeBot(), ctx, "zzzzzzzzzz")

    context = search_context.get(ctx.sent[0].id)
    assert context["top_title"] is None
    assert context["top_url"] is None
    assert stats.trending("test") == [{"query": "zzzzzzzzzz", "count": 1}]


# --- rejected input and failures ---------------------------------------------


def test_an_over_long_query_is_rejected_before_the_database(
    game_db, ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("the database must not be touched")

    monkeypatch.setattr(search_flow, "search_pages_async", explode)

    run_search(FakeBot(), ctx, "x" * (settings.max_query_length + 1))

    assert "Запит задовгий" in ctx.texts[0]


def test_a_database_failure_is_reported_not_raised(
    game_db, ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(search_flow, "search_pages_async", broken)

    run_search(FakeBot(), ctx, "absolutism")

    assert "Не вдалося виконати пошук" in ctx.texts[0]


def test_a_stats_failure_does_not_lose_the_results(
    game_db, ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bookkeeping is not worth failing a search the user already paid for."""
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")

    def broken(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(search_flow.stats, "record_search", broken)

    run_search(FakeBot(), ctx, "absolutism")

    assert ctx.embeds[0].title == "Absolutism"


def test_a_suggestion_failure_still_sends_the_not_found_embed(
    game_db, ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(search_flow, "suggest_similar_async", broken)

    run_search(FakeBot(), ctx, "zzzzzzzzzz")

    assert "нічого не знайдено" in ctx.embeds[0].title
    assert ctx.sent[0].view is None


def test_a_failed_reaction_does_not_fail_the_search(
    game_db, ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing "Add Reactions" in a channel must not swallow the results."""
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")

    async def refuse(self: object, emoji: str) -> None:
        raise http_error("missing permissions")

    monkeypatch.setattr("conftest.FakeMessage.add_reaction", refuse)

    run_search(FakeBot(), ctx, "absolutism")

    assert ctx.embeds[0].title == "Absolutism"


# --- mirroring into the log channel ------------------------------------------


def test_no_log_channel_configured_sends_nothing(game_db, ctx: FakeContext) -> None:
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")
    bot = FakeBot()

    run_search(bot, ctx, "absolutism")

    assert bot.asked_for == []


def test_the_request_is_mirrored_into_the_log_channel(
    game_db, ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "log_channel_id", 999)
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism", "https://img/a.png")
    channel = FakeSendable()

    run_search(FakeBot(channel), ctx, "absolutism")

    embed = channel.embeds[0]
    assert embed.title == "📄 Paradox Wiki Запит"
    values = {field.name: field.value for field in embed.fields}
    assert values["**User**"] == f"<@{ctx.author.id}>"
    assert values["**Request**"] == f"`{settings.bot_prefix}test absolutism`"
    assert "Знайдено: так" in values["**Result**"]
    assert "Картинка: так" in values["**Result**"]


def test_an_uncached_log_channel_is_survivable(
    game_db, ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "log_channel_id", 999)
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")

    run_search(FakeBot(None), ctx, "absolutism")

    assert ctx.embeds[0].title == "Absolutism"


def test_a_log_channel_that_cannot_receive_messages_is_survivable(
    game_db, ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LOG_CHANNEL_ID pointing at a category or voice channel, say."""
    monkeypatch.setattr(settings, "log_channel_id", 999)
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")

    run_search(FakeBot(object()), ctx, "absolutism")

    assert ctx.embeds[0].title == "Absolutism"


def test_a_failing_log_channel_does_not_fail_the_search(
    game_db, ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BrokenChannel(FakeSendable):
        async def send(self, content=None, *, embed=None, view=None):  # type: ignore[override]
            raise http_error("forbidden")

    monkeypatch.setattr(settings, "log_channel_id", 999)
    insert_page(game_db, "Absolutism", "https://wiki/Absolutism")

    run_search(FakeBot(BrokenChannel()), ctx, "absolutism")

    assert ctx.embeds[0].title == "Absolutism"
