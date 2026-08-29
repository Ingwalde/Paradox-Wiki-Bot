from __future__ import annotations

import asyncio

from sqlalchemy import text

from paradox_bot import db_migrate, storage


async def test_run_migrations_brings_up_the_writable_tables(db: None) -> None:
    engine = storage.get_engine()
    # Start from nothing the migration is responsible for.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DROP TABLE IF EXISTS uploads, feedback, search_log, api_cache, "
                "alembic_version CASCADE"
            )
        )

    # Alembic is synchronous and drives its own loop, so it runs in a thread.
    await asyncio.to_thread(db_migrate.run_migrations)

    async with engine.connect() as conn:
        for table in ("uploads", "feedback", "search_log", "api_cache"):
            exists = await conn.scalar(text(f"SELECT to_regclass('public.{table}')"))
            assert exists is not None, table
