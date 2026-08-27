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


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring a Feedback table created before vote dedup up to date.

    message_id and the unique index below are what make one row mean one
    user's opinion of one result message. Without them a user could toggle a
    reaction off and on to write a row per toggle, inflating /admin feedback
    and any measurement of search quality built on this table.

    Rows written before the column existed keep message_id NULL. SQLite treats
    NULLs as distinct in a unique index, so they neither collide with each
    other nor block the index -- old rows simply stay un-deduplicated, which
    is the best that can be said about votes whose message was never recorded.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(Feedback)")}
    if "message_id" not in columns:
        conn.execute("ALTER TABLE Feedback ADD COLUMN message_id TEXT")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_message_user "
        "ON Feedback(message_id, user_id)"
    )


def _connect() -> sqlite3.Connection:
    return storage.connect(settings.feedback_db_path, storage.FEEDBACK_SCHEMA, _migrate)


def record_feedback(
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
    adding a row: a user who switches ✅ to ❌ has one opinion, not two.

    Blocking; call via asyncio.to_thread.
    """
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO Feedback "
            "(message_id, user_id, game_key, query, vote, top_title, top_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(message_id, user_id) DO UPDATE SET "
            "vote = excluded.vote, timestamp = CURRENT_TIMESTAMP",
            (message_id, user_id, game_key, query, vote, top_title, top_url),
        )
        conn.commit()
    finally:
        conn.close()


def recent_feedback(limit: int = 10) -> list[dict[str, Any]]:
    """Return the most recent votes, newest first. Blocking; call via asyncio.to_thread."""
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT user_id, game_key, query, vote, top_title, top_url, timestamp "
            "FROM Feedback ORDER BY timestamp DESC, id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.OperationalError:
        # Reachable only if the file was removed after this process cached its
        # schema as applied; storage.connect() creates the table otherwise.
        return []
    finally:
        conn.close()
