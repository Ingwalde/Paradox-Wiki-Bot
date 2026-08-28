"""The -tools upload flow.

The riskiest command in the bot: it waits for an attachment, size-checks it,
uploads, handles a duplicate, and records the result. Every branch is asserted
here on what the user would actually see.

Invoked through `.callback(cog, ctx)` to bypass the cooldown/max_concurrency
wrappers, which are asserted separately in test_bot_limits.py.
"""

from __future__ import annotations

import asyncio

import discord
import pytest

from paradox_bot import pdx_tools
from paradox_bot.cogs.tools import ToolsCog
from paradox_bot.config import settings
from tests.conftest import FakeContext


class FakeAttachment:
    def __init__(self, filename: str = "save.eu4", size: int = 1024, data: bytes = b"data"):
        self.filename = filename
        self.size = size
        self._data = data
        self.read_error: Exception | None = None

    async def read(self) -> bytes:
        if self.read_error is not None:
            raise self.read_error
        return self._data


class FakeBot:
    """Supplies the attachment message that -tools waits for."""

    def __init__(self, attachment: FakeAttachment | None) -> None:
        self._attachment = attachment

    async def wait_for(self, _event: str, *, timeout: float, check) -> object:
        if self._attachment is None:
            raise TimeoutError
        return type("Msg", (), {"attachments": [self._attachment]})()


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch):
    """Credentials present, unless a test says otherwise."""
    monkeypatch.setattr(settings, "pdx_tools_user_id", "user-42")
    monkeypatch.setattr(settings, "pdx_tools_api_key", "secret")


def _cog(attachment: FakeAttachment | None = None) -> ToolsCog:
    return ToolsCog(bot=FakeBot(attachment if attachment else FakeAttachment()))


def test_says_so_when_credentials_are_missing(ctx: FakeContext, monkeypatch) -> None:
    monkeypatch.setattr(settings, "pdx_tools_api_key", "")
    cog = _cog()
    asyncio.run(cog.tools.callback(cog, ctx))
    assert "не налаштоване" in ctx.texts[0]
    # It must not go on to ask for a file it cannot do anything with.
    assert len(ctx.texts) == 1


def test_reports_a_timeout_when_no_file_arrives(ctx: FakeContext) -> None:
    cog = ToolsCog(bot=FakeBot(None))
    asyncio.run(cog.tools.callback(cog, ctx))
    assert "Час очікування вичерпано" in ctx.texts[-1]


def test_rejects_an_oversized_attachment(ctx: FakeContext, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_save_bytes", 1024 * 1024)
    cog = _cog(FakeAttachment(size=50 * 1024 * 1024))
    asyncio.run(cog.tools.callback(cog, ctx))
    assert "завеликий" in ctx.texts[-1]
    # Rejected before reading it into memory, so no progress message was sent.
    assert not any("Завантажую" in t for t in ctx.texts)


async def test_successful_upload_reports_the_real_url(ctx: FakeContext, monkeypatch, db) -> None:
    async def fake_upload(_filename: str, _payload: bytes) -> str:
        return "https://pdx.tools/eu4/saves/abc123"

    monkeypatch.setattr("paradox_bot.cogs.tools.upload_to_pdx_tools", fake_upload)
    cog = _cog()
    await cog.tools.callback(cog, ctx)

    assert ctx.texts[-1] == "✅ Завантажено: https://pdx.tools/eu4/saves/abc123"
    # The progress message is cleaned up rather than left dangling.
    progress = [m for m in ctx.sent if m.content and "Завантажую" in m.content]
    assert progress and progress[0].deleted


async def test_successful_upload_is_recorded(ctx: FakeContext, monkeypatch, db) -> None:
    async def fake_upload(_filename: str, _payload: bytes) -> str:
        return "https://pdx.tools/eu4/saves/abc123"

    monkeypatch.setattr("paradox_bot.cogs.tools.upload_to_pdx_tools", fake_upload)
    cog = _cog()
    await cog.tools.callback(cog, ctx)

    assert (
        await pdx_tools.find_prior_upload_url("save.eu4")
        == "https://pdx.tools/eu4/saves/abc123"
    )


async def test_duplicate_returns_the_previously_recorded_link(
    ctx: FakeContext, monkeypatch, db
) -> None:
    await pdx_tools.record_upload("42", "save.eu4", "https://pdx.tools/eu4/saves/older")

    async def duplicate(_filename: str, _payload: bytes) -> str:
        raise pdx_tools.PdxDuplicateSaveError('{"msg": "save already exists"}')

    monkeypatch.setattr("paradox_bot.cogs.tools.upload_to_pdx_tools", duplicate)
    cog = _cog()
    await cog.tools.callback(cog, ctx)

    assert ctx.texts[-1] == "✅ Завантажено: https://pdx.tools/eu4/saves/older"


async def test_duplicate_without_a_record_points_at_the_account_page(
    ctx: FakeContext, monkeypatch, db
) -> None:
    async def duplicate(_filename: str, _payload: bytes) -> str:
        raise pdx_tools.PdxDuplicateSaveError('{"msg": "save already exists"}')

    monkeypatch.setattr("paradox_bot.cogs.tools.upload_to_pdx_tools", duplicate)
    cog = _cog()
    await cog.tools.callback(cog, ctx)

    message = ctx.texts[-1]
    assert "уже завантажено" in message
    # Never invent a save URL: point at the account page instead.
    assert "pdx.tools/account" in message
    assert "save.eu4" not in message


def test_api_rejection_is_surfaced(ctx: FakeContext, monkeypatch) -> None:
    async def rejected(_filename: str, _payload: bytes) -> str:
        raise pdx_tools.PdxToolsError("HTTP 400: no save slots")

    monkeypatch.setattr("paradox_bot.cogs.tools.upload_to_pdx_tools", rejected)
    cog = _cog()
    asyncio.run(cog.tools.callback(cog, ctx))
    assert "відхилив завантаження" in ctx.texts[-1]
    assert "no save slots" in ctx.texts[-1]


def test_unreadable_attachment_is_reported(ctx: FakeContext) -> None:
    attachment = FakeAttachment()
    attachment.read_error = discord.HTTPException(
        type("R", (), {"status": 500, "reason": "err"})(), "boom"
    )
    cog = _cog(attachment)
    asyncio.run(cog.tools.callback(cog, ctx))
    assert "Не вдалося прочитати вкладення" in ctx.texts[-1]


def test_unexpected_error_does_not_leak_a_traceback(ctx: FakeContext, monkeypatch) -> None:
    async def boom(_filename: str, _payload: bytes) -> str:
        raise RuntimeError("something nobody predicted")

    monkeypatch.setattr("paradox_bot.cogs.tools.upload_to_pdx_tools", boom)
    cog = _cog()
    asyncio.run(cog.tools.callback(cog, ctx))

    assert "Несподівана помилка" in ctx.texts[-1]
    assert "something nobody predicted" not in ctx.texts[-1]


def test_bookkeeping_failure_does_not_hide_a_successful_upload(
    ctx: FakeContext, monkeypatch
) -> None:
    from paradox_bot.storage import StorageError

    async def fake_upload(_filename: str, _payload: bytes) -> str:
        return "https://pdx.tools/eu4/saves/abc123"

    async def broken_record(*_args: object) -> None:
        raise StorageError("database is locked")

    monkeypatch.setattr("paradox_bot.cogs.tools.upload_to_pdx_tools", fake_upload)
    monkeypatch.setattr("paradox_bot.cogs.tools.record_upload", broken_record)
    cog = _cog()
    asyncio.run(cog.tools.callback(cog, ctx))

    # The upload really happened; a failed local write must not turn it into an error.
    assert ctx.texts[-1] == "✅ Завантажено: https://pdx.tools/eu4/saves/abc123"
