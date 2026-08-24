from __future__ import annotations

import asyncio
import types
from typing import Any

import discord
import pytest

from paradox_bot.games import GameInfo
from paradox_bot.ui.views import PaginatedResultsView

GAME = GameInfo(key="test", name="Test Game", color=0, logo="", wiki_subdomain="test")


def _pages(count: int) -> list[dict[str, Any]]:
    return [
        {"title": f"Page {i}", "url": f"https://test.paradoxwikis.com/Page_{i}", "image_url": ""}
        for i in range(count)
    ]


class _FakeResponse:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []

    async def send_message(self, content: str, ephemeral: bool = False) -> None:
        self.messages.append((content, ephemeral))


def _interaction(user_id: int) -> Any:
    return types.SimpleNamespace(
        user=types.SimpleNamespace(id=user_id), response=_FakeResponse()
    )


def test_author_may_paginate() -> None:
    view = PaginatedResultsView(_pages(20), GAME, author_id=7)
    assert asyncio.run(view.interaction_check(_interaction(7))) is True


def test_other_users_may_not_paginate() -> None:
    view = PaginatedResultsView(_pages(20), GAME, author_id=7)
    interaction = _interaction(99)
    assert asyncio.run(view.interaction_check(interaction)) is False
    # And they are told why, privately, rather than silently ignored.
    (content, ephemeral) = interaction.response.messages[0]
    assert ephemeral is True
    assert "чужий пошук" in content


def test_timeout_disables_navigation_and_edits_the_message() -> None:
    view = PaginatedResultsView(_pages(20), GAME, author_id=7)
    edited: dict[str, Any] = {}

    class _Message:
        async def edit(self, **kwargs: Any) -> None:
            edited.update(kwargs)

    view.message = _Message()  # type: ignore[assignment]
    asyncio.run(view.on_timeout())

    nav = [item for item in view.children if getattr(item, "url", None) is None]
    assert nav, "expected navigation buttons for 20 results"
    assert all(item.disabled for item in nav)
    assert edited.get("view") is view


def test_timeout_leaves_link_buttons_alone() -> None:
    # Link buttons carry a url and are never interactive, so Discord rejects
    # them being marked disabled the way a callback button is.
    view = PaginatedResultsView(_pages(20), GAME, author_id=7)
    asyncio.run(view.on_timeout())
    links = [item for item in view.children if getattr(item, "url", None)]
    assert links
    assert not any(item.disabled for item in links)


def test_timeout_without_a_message_is_a_noop() -> None:
    view = PaginatedResultsView(_pages(20), GAME, author_id=7)
    asyncio.run(view.on_timeout())  # message is None; must not raise


def test_timeout_survives_a_deleted_message() -> None:
    view = PaginatedResultsView(_pages(20), GAME, author_id=7)

    class _Gone:
        async def edit(self, **kwargs: Any) -> None:
            raise discord.HTTPException(_FakeHTTPResponse(), "Unknown Message")

    view.message = _Gone()  # type: ignore[assignment]
    asyncio.run(view.on_timeout())


class _FakeHTTPResponse:
    status = 404
    reason = "Not Found"


@pytest.mark.parametrize(("count", "expected"), [(1, 1), (7, 1), (8, 2), (35, 5)])
def test_page_count(count: int, expected: int) -> None:
    assert PaginatedResultsView(_pages(count), GAME, author_id=1).total_pages == expected


def test_single_page_has_no_navigation() -> None:
    view = PaginatedResultsView(_pages(3), GAME, author_id=1)
    assert all(getattr(item, "url", None) for item in view.children)
