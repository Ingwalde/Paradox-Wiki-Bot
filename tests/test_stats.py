from __future__ import annotations

from sqlalchemy import text

from paradox_bot import stats
from paradox_bot.storage import session


async def test_trending_empty_returns_empty(db: None) -> None:
    assert await stats.trending("eu4") == []


async def test_trending_counts_and_orders_by_frequency(db: None) -> None:
    await stats.record_search("eu4", "absolutism")
    await stats.record_search("eu4", "absolutism")
    await stats.record_search("eu4", "prussia")
    rows = await stats.trending("eu4")
    assert rows[0]["query"] == "absolutism"
    assert rows[0]["count"] == 2
    assert rows[1]["query"] == "prussia"
    assert rows[1]["count"] == 1


async def test_trending_groups_case_insensitively(db: None) -> None:
    await stats.record_search("eu4", "Absolutism")
    await stats.record_search("eu4", "absolutism")
    rows = await stats.trending("eu4")
    assert len(rows) == 1
    assert rows[0]["count"] == 2


async def test_trending_is_scoped_to_game(db: None) -> None:
    await stats.record_search("eu4", "absolutism")
    await stats.record_search("hoi4", "germany")
    rows = await stats.trending("eu4")
    assert [r["query"] for r in rows] == ["absolutism"]


async def test_trending_respects_limit(db: None) -> None:
    for query in ("a", "b", "c", "d"):
        await stats.record_search("eu4", query)
    assert len(await stats.trending("eu4", limit=2)) == 2


async def test_trending_excludes_old_searches(db: None) -> None:
    await stats.record_search("eu4", "absolutism")
    async with session() as sess:
        await sess.execute(
            text("UPDATE search_log SET timestamp = now() - interval '30 days' "
                 "WHERE query = :q"),
            {"q": "absolutism"},
        )
    assert await stats.trending("eu4", days=7) == []
