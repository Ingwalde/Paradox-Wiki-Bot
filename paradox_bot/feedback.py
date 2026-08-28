"""Persisted ✅/❌ votes on search results.

Only persistence. The in-memory message->query correlation the reaction
handler needs lives in search_context.py, and the Ukrainian pluralizer it
used to carry is presentation -- it lives in ui/text.py.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from paradox_bot.storage import Feedback, session

FEEDBACK_EMOJIS = {"✅": "up", "❌": "down"}


async def record_feedback(
    message_id: str,
    user_id: str,
    game_key: str,
    query: str,
    vote: str,
    top_title: str | None,
    top_url: str | None,
) -> None:
    """Persist a ✅/❌ vote, one per user per result message.

    Voting again on the same message replaces the earlier vote rather than
    adding a row: a user who switches ✅ to ❌ has one opinion, not two. The
    (message_id, user_id) unique constraint drives the ON CONFLICT below.

    Raises:
        StorageError: If the write fails.
    """
    insert_stmt = pg_insert(Feedback).values(
        message_id=message_id,
        user_id=user_id,
        game_key=game_key,
        query=query,
        vote=vote,
        top_title=top_title,
        top_url=top_url,
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[Feedback.message_id, Feedback.user_id],
        set_={"vote": insert_stmt.excluded.vote, "timestamp": func.now()},
    )
    async with session() as sess:
        await sess.execute(stmt)


async def recent_feedback(limit: int = 10) -> list[dict[str, Any]]:
    """Return the most recent votes, newest first.

    Raises:
        StorageError: If the read fails.
    """
    stmt = (
        select(
            Feedback.user_id,
            Feedback.game_key,
            Feedback.query,
            Feedback.vote,
            Feedback.top_title,
            Feedback.top_url,
            Feedback.timestamp,
        )
        .order_by(Feedback.timestamp.desc(), Feedback.id.desc())
        .limit(limit)
    )
    async with session() as sess:
        result = await sess.execute(stmt)
        return [dict(row) for row in result.mappings()]
