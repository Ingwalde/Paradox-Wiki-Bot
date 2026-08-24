"""Persisted ✅/❌ votes on search results.

Only persistence. The in-memory message->query correlation the reaction
handler needs lives in search_context.py, and the Ukrainian pluralizer it
used to carry is presentation -- it lives in ui/text.py.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from paradox_bot import storage
from paradox_bot.config import settings

FEEDBACK_EMOJIS = {"✅": "up", "❌": "down"}

def record_feedback(
    user_id: str,
    game_key: str,
    query: str,
    vote: str,
    top_title: str | None,
    top_url: str | None,
) -> None:
    """Persist a ✅/❌ vote. Blocking; call via asyncio.to_thread."""
    conn = storage.connect(settings.feedback_db_path, storage.FEEDBACK_SCHEMA)
    try:
        conn.execute(
            "INSERT INTO Feedback (user_id, game_key, query, vote, top_title, top_url) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, game_key, query, vote, top_title, top_url),
        )
        conn.commit()
    finally:
        conn.close()


def recent_feedback(limit: int = 10) -> list[dict[str, Any]]:
    """Return the most recent votes, newest first. Blocking; call via asyncio.to_thread."""
    conn = storage.connect(settings.feedback_db_path, storage.FEEDBACK_SCHEMA)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT user_id, game_key, query, vote, top_title, top_url, timestamp "
            "FROM Feedback ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.OperationalError:
        # Reachable only if the file was removed after this process cached its
        # schema as applied; storage.connect() creates the table otherwise.
        return []
    finally:
        conn.close()
