"""Search-frequency tracking for the -trending command."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from paradox_bot.storage import SearchLog, session


async def record_search(game_key: str, query: str) -> None:
    """Log a search.

    Raises:
        StorageError: If the write fails.
    """
    async with session() as sess:
        sess.add(SearchLog(game_key=game_key, query=query))


async def trending(game_key: str, days: int = 7, limit: int = 5) -> list[dict[str, Any]]:
    """Most frequent queries for a game in the last `days` days, newest tie-winner first.

    Queries are grouped case-insensitively; the representative shown for each
    group is min(query), a deterministic member of the group (Postgres, unlike
    SQLite, will not return a bare non-grouped column). Ties on frequency are
    broken by the most recent row's id, so the freshest query wins.

    Raises:
        StorageError: If the read fails.
    """
    count = func.count().label("count")
    stmt = (
        select(func.min(SearchLog.query).label("query"), count)
        .where(
            SearchLog.game_key == game_key,
            # make_interval's fourth positional argument is `days`.
            SearchLog.timestamp >= func.now() - func.make_interval(0, 0, 0, days),
        )
        .group_by(func.lower(SearchLog.query))
        .order_by(count.desc(), func.max(SearchLog.id).desc())
        .limit(limit)
    )
    async with session() as sess:
        result = await sess.execute(stmt)
        return [dict(row) for row in result.mappings()]
