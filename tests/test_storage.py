from __future__ import annotations

import pytest
from sqlalchemy import select, text

from paradox_bot import storage
from paradox_bot.config import settings
from tests.conftest import TEST_DATABASE_URL


async def test_check_db_true_when_reachable(db: None) -> None:
    assert await storage.check_db() is True


async def test_check_db_false_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Nothing listens on port 1; the probe must return False, not raise.
    storage.init_engine("postgresql+asyncpg://postgres@127.0.0.1:1/paradox")
    monkeypatch.setattr(settings, "db_health_timeout_seconds", 1.0)
    try:
        assert await storage.check_db() is False
    finally:
        await storage.dispose_engine()


async def test_wait_for_db_returns_when_reachable(db: None) -> None:
    await storage.wait_for_db()  # must not raise


async def test_wait_for_db_raises_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "db_connect_retries", 2)
    monkeypatch.setattr(settings, "db_connect_base_delay", 0.01)
    storage.init_engine("postgresql+asyncpg://postgres@127.0.0.1:1/paradox")
    try:
        with pytest.raises(storage.StorageError):
            await storage.wait_for_db()
    finally:
        await storage.dispose_engine()


async def test_session_translates_driver_errors_into_storage_error(db: None) -> None:
    with pytest.raises(storage.StorageError):
        async with storage.session() as sess:
            await sess.execute(text("SELECT * FROM table_that_does_not_exist"))


async def test_identity_primary_key_is_assigned_by_the_database(db: None) -> None:
    async with storage.session() as sess:
        row = storage.Uploads(user_id="u", filename="a.eu4", url="https://x")
        sess.add(row)
        await sess.flush()
        assert row.id is not None


async def test_created_at_defaults_to_now(db: None) -> None:
    async with storage.session() as sess:
        sess.add(storage.SearchLog(game_key="eu4", query="rome"))
    async with storage.session() as sess:
        stamp = await sess.scalar(select(storage.SearchLog.timestamp))
    assert stamp is not None


def test_engine_is_reused_for_the_default_url() -> None:
    storage.init_engine(TEST_DATABASE_URL)
    first = storage.get_engine()
    # A second call with no explicit URL keeps the same engine.
    assert storage.init_engine() is first
