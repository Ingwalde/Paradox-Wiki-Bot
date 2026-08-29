"""PostgreSQL-backed wiki page search: direct titles plus redirects, ranked.

The ranking query is deliberately raw SQL (sqlalchemy.text): it does relevance
ranking across a UNION of pages and redirects that the ORM would only obscure.
The CRUD around the writable tables uses the ORM; this does not.
"""

from __future__ import annotations

import difflib
from typing import Any

from sqlalchemy import func, select, text

from paradox_bot.config import settings
from paradox_bot.storage import Pages, Redirects, session

FUZZY_MATCH_LIMIT = 5
FUZZY_MATCH_CUTOFF = 0.6


def normalize(text: str) -> str:
    """Fold a title or query into the form used for comparison."""
    return text.lower().replace("_", " ").strip()


def escape_like(text: str) -> str:
    """Escape LIKE wildcards so a query of '100%' is matched literally."""
    for char in ("\\", "%", "_"):
        text = text.replace(char, f"\\{char}")
    return text


# Redirects.target_page_url may carry a #section fragment (e.g. a patch-notes
# anchor); the base page it points at is everything before that fragment.
# split_part is Postgres' one-call replacement for SQLite's instr()/substr().
_STRIP_FRAGMENT_SQL = "split_part(r.target_page_url, '#', 1)"

# DISTINCT ON (title) collapses the several redirects that can point at one page
# (each with a different #fragment) down to one row -- Postgres rejects the bare
# columns SQLite allowed under GROUP BY, so the best-ranked row per title is
# picked by the inner ORDER BY and the final ordering is applied outside.
_SEARCH_SQL = text(
    f"""
WITH matches AS (
    SELECT
        title, url, image_url,
        CASE
            WHEN lower(replace(title, '_', ' ')) = :exact THEN 0
            WHEN lower(replace(title, '_', ' ')) LIKE :prefix ESCAPE '\\' THEN 1
            ELSE 2
        END AS rank
    FROM pages
    WHERE game_key = :game
      AND lower(replace(title, '_', ' ')) LIKE :contains ESCAPE '\\'

    UNION ALL

    SELECT
        p.title, r.target_page_url AS url, p.image_url,
        CASE
            WHEN lower(replace(r.redirect_title, '_', ' ')) = :exact THEN 0
            WHEN lower(replace(r.redirect_title, '_', ' ')) LIKE :prefix ESCAPE '\\' THEN 1
            ELSE 2
        END AS rank
    FROM redirects r
    JOIN pages p ON p.url = {_STRIP_FRAGMENT_SQL} AND p.game_key = r.game_key
    WHERE r.game_key = :game
      AND lower(replace(r.redirect_title, '_', ' ')) LIKE :contains ESCAPE '\\'
)
SELECT title, url, image_url, best_rank
FROM (
    SELECT DISTINCT ON (title) title, url, image_url, rank AS best_rank
    FROM matches
    ORDER BY title, rank, length(title)
) ranked
ORDER BY best_rank, length(title), title
LIMIT :limit
"""
)


async def search_pages(
    game_key: str, query: str, limit: int | None = None
) -> list[dict[str, Any]]:
    """Find wiki pages matching a query, via direct titles and redirects.

    Ranking: exact title/redirect match first, then names starting with the
    query, then names containing it elsewhere; ties broken by title length
    (shorter, more likely canonical titles first) then alphabetically.

    Args:
        game_key: One of the keys in GAMES.
        query: Raw user query.
        limit: Maximum number of results (defaults to settings.search_result_limit).

    Returns:
        Page dicts with title, url and image_url keys.

    Raises:
        StorageError: If the database is unreachable.
    """
    normalized = normalize(query)
    if not normalized:
        return []
    if limit is None:
        limit = settings.search_result_limit

    escaped = escape_like(normalized)
    async with session() as sess:
        result = await sess.execute(
            _SEARCH_SQL,
            {
                "game": game_key,
                "exact": normalized,
                "prefix": f"{escaped}%",
                "contains": f"%{escaped}%",
                "limit": limit,
            },
        )
        return [
            {"title": row.title, "url": row.url, "image_url": row.image_url}
            for row in result
        ]


async def random_page(game_key: str) -> dict[str, Any] | None:
    """Return a random page for the game, or None if it has no pages yet.

    Raises:
        StorageError: If the database is unreachable.
    """
    stmt = (
        select(Pages.title, Pages.url, Pages.image_url)
        .where(Pages.game_key == game_key)
        .order_by(func.random())
        .limit(1)
    )
    async with session() as sess:
        row = (await sess.execute(stmt)).first()
        return dict(row._mapping) if row else None


async def suggest_similar(
    game_key: str, query: str, limit: int = FUZZY_MATCH_LIMIT
) -> list[dict[str, Any]]:
    """Fuzzy "did you mean" suggestions for when search_pages finds nothing.

    Only meant for the empty-result path: it loads every title in the game's
    pages and fuzzy-matches with difflib, too slow to run on every search but
    cheap for the rare case of zero hits at a few thousand rows per game.

    Raises:
        StorageError: If the database is unreachable.
    """
    normalized = normalize(query)
    if not normalized:
        return []

    stmt = select(Pages.title, Pages.url, Pages.image_url).where(Pages.game_key == game_key)
    async with session() as sess:
        rows = (await sess.execute(stmt)).all()

    # If two titles normalize the same, the later one silently wins; harmless
    # for a "did you mean" hint.
    by_normalized = {normalize(row.title): row for row in rows}
    close = difflib.get_close_matches(
        normalized, by_normalized.keys(), n=limit, cutoff=FUZZY_MATCH_CUTOFF
    )
    return [dict(by_normalized[title]._mapping) for title in close]


async def db_stats(game_key: str) -> dict[str, Any] | None:
    """Return {"pages", "redirects", "modified"} for a game, or None if it has
    no pages loaded. Used by the /admin status command.

    "modified" is the newest imported_at in the game's pages, as a POSIX
    timestamp (there is no per-game file mtime any more).

    Raises:
        StorageError: If the database is unreachable.
    """
    async with session() as sess:
        pages = await sess.scalar(
            select(func.count()).select_from(Pages).where(Pages.game_key == game_key)
        )
        if not pages:
            return None
        redirects = await sess.scalar(
            select(func.count()).select_from(Redirects).where(Redirects.game_key == game_key)
        )
        modified = await sess.scalar(
            select(func.max(Pages.imported_at)).where(Pages.game_key == game_key)
        )

    # pages > 0 guarantees at least one row, and imported_at is NOT NULL, so the
    # MAX is a real timestamp -- the None arm only exists in the column's type.
    assert modified is not None
    return {
        "pages": pages,
        "redirects": redirects,
        "modified": modified.timestamp(),
    }
