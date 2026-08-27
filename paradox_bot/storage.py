"""Shared SQLite connection handling for the bot's writable databases.

The read-only game databases in `settings.db_dir` are opened by
`paradox_bot.search` with their own `mode=ro` URI; this module is only for the
three files the bot writes to.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from paradox_bot.config import settings

UPLOADS_SCHEMA = """
CREATE TABLE IF NOT EXISTS Uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    filename TEXT,
    url TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

FEEDBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS Feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT,
    user_id TEXT,
    game_key TEXT,
    query TEXT,
    vote TEXT,
    top_title TEXT,
    top_url TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

SEARCH_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS SearchLog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_key TEXT,
    query TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

# Paths whose schema this process has already applied. The DDL used to run on
# every single write; it only ever needs to run once per file per process.
_schema_applied: set[Path] = set()


def reset_schema_cache() -> None:
    """Forget which files have been initialised. For tests."""
    _schema_applied.clear()


def connect(
    path: Path,
    schema: str,
    migrate: Callable[[sqlite3.Connection], None] | None = None,
) -> sqlite3.Connection:
    """Open a writable database with WAL enabled and its schema in place.

    WAL matters for more than concurrency here: the container is stopped with
    SIGTERM and killed nine seconds later, and a write-ahead log recovers from
    an abrupt termination far more reliably than the default rollback journal.
    `synchronous=NORMAL` is the standard pairing — durable across a process
    crash, which is the failure being defended against, while not paying an
    fsync per transaction.

    `migrate` runs once per file per process, straight after the schema, for
    changes `CREATE TABLE IF NOT EXISTS` cannot make: on a database that
    already has the table the DDL above is a no-op, so a column or index added
    after that file first shipped has to be applied explicitly. It must be
    safe to run against a table that is already up to date.

    Blocking; call via asyncio.to_thread.
    """
    conn = sqlite3.connect(path, timeout=settings.db_timeout_seconds)
    try:
        # journal_mode is persisted in the file, so this is a no-op after the
        # first time; synchronous is per-connection and must be set each time.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

        resolved = Path(path).resolve()
        if resolved not in _schema_applied:
            conn.executescript(schema)
            if migrate is not None:
                migrate(conn)
            conn.commit()
            _schema_applied.add(resolved)
    except Exception:
        conn.close()
        raise
    return conn
