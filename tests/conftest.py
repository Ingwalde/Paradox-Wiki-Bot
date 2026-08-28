"""Shared fixtures for the test suite."""

from __future__ import annotations

import itertools
import os
import sqlite3
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import discord
import pytest
import pytest_asyncio
from sqlalchemy import text

# The writable tables live in Postgres. Point the tests at a throwaway database:
# the CI `test` job supplies TEST_DATABASE_URL for its `postgres` service, and a
# local run falls back to a developer's own instance.
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres@127.0.0.1:5432/paradox"
)


@pytest_asyncio.fixture()
async def db() -> AsyncIterator[None]:
    """Point storage at the test database with the schema present and empty.

    A single engine per test (bound to that test's event loop, which asyncpg
    requires), the ORM schema created if missing, and every table truncated so
    each test starts from a clean slate regardless of order.
    """
    from paradox_bot import storage

    storage.init_engine(TEST_DATABASE_URL)
    engine = storage.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(storage.Base.metadata.create_all)
        tables = ", ".join(t.name for t in storage.Base.metadata.sorted_tables)
        if tables:
            await conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    try:
        yield
    finally:
        await storage.dispose_engine()


@pytest.fixture()
def game_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Build a throwaway 'test' game database wired into paradox_bot.search."""
    from paradox_bot.config import settings
    from paradox_bot.games import GAMES, GameInfo

    db_dir = tmp_path / "databases"
    db_dir.mkdir()
    db_file = db_dir / "test.db"

    conn = sqlite3.connect(db_file)
    conn.executescript(
        """
        CREATE TABLE Pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT UNIQUE,
            url TEXT UNIQUE,
            image_url TEXT,
            lang TEXT
        );
        CREATE TABLE Redirects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            redirect_title TEXT,
            redirect_url TEXT,
            target_page_url TEXT,
            FOREIGN KEY(target_page_url) REFERENCES Pages(url)
        );
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "db_dir", db_dir)
    monkeypatch.setitem(
        GAMES,
        "test",
        GameInfo(key="test", name="Test Game", color=0, logo="", wiki_subdomain="test"),
    )
    yield db_file
    del GAMES["test"]


class FakeMessage:
    """Stands in for a sent discord.Message: records what it was sent with."""

    # search_flow keys its per-message search context off message.id, so a
    # fake message needs one too. Only uniqueness matters, not the shape of a
    # real Discord snowflake.
    _next_id = itertools.count(1)

    def __init__(self, content: str | None, embed: object, view: object) -> None:
        self.id = next(FakeMessage._next_id)
        self.content = content
        self.embed = embed
        self.view = view
        self.deleted = False
        self.reactions: list[str] = []

    async def delete(self) -> None:
        self.deleted = True

    async def add_reaction(self, emoji: str) -> None:
        self.reactions.append(emoji)


class FakeSendable(discord.abc.Messageable):
    """Records ctx.send(...) / channel.send(...) calls instead of hitting Discord.

    The cogs only ever call .send() on a context or channel, so recording that
    one method is enough to assert on what a user would have seen -- no mocking
    of the Discord client, gateway or HTTP layer.

    Subclasses discord.abc.Messageable (a plain mixin class, not an ABC) so the
    daily-fact loop's isinstance guard lets it through. `send` is overridden
    outright, so none of the inherited HTTP machinery is reachable.
    """

    def __init__(self) -> None:
        self.sent: list[FakeMessage] = []

    async def send(
        self, content: str | None = None, *, embed: object = None, view: object = None
    ) -> FakeMessage:
        message = FakeMessage(content, embed, view)
        self.sent.append(message)
        return message

    @property
    def texts(self) -> list[str]:
        return [m.content for m in self.sent if m.content is not None]

    @property
    def embeds(self) -> list[object]:
        return [m.embed for m in self.sent if m.embed is not None]


class FakeAuthor:
    def __init__(self, user_id: int = 42) -> None:
        self.id = user_id


class FakeContext(FakeSendable):
    """Minimal commands.Context stand-in: .send(), .author, .channel."""

    def __init__(self, user_id: int = 42) -> None:
        super().__init__()
        self.author = FakeAuthor(user_id)
        self.channel = object()


class FakeResponse:
    """discord.InteractionResponse stand-in for the slash commands."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(
        self, content: str | None = None, *, embed: object = None, ephemeral: bool = False
    ) -> None:
        self.sent.append({"content": content, "embed": embed, "ephemeral": ephemeral})


class FakeInteraction:
    def __init__(self) -> None:
        self.response = FakeResponse()


@pytest.fixture()
def ctx() -> FakeContext:
    return FakeContext()


@pytest.fixture()
def interaction() -> FakeInteraction:
    return FakeInteraction()


def insert_page(db_file: Path, title: str, url: str, image_url: str = "") -> None:
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "INSERT INTO Pages (title, url, image_url) VALUES (?, ?, ?)",
            (title, url, image_url),
        )
        conn.commit()
    finally:
        conn.close()


def insert_redirect(db_file: Path, redirect_title: str, target_page_url: str) -> None:
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "INSERT INTO Redirects (redirect_title, redirect_url, target_page_url) "
            "VALUES (?, '', ?)",
            (redirect_title, target_page_url),
        )
        conn.commit()
    finally:
        conn.close()
