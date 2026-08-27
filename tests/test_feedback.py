from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from paradox_bot import feedback, storage
from paradox_bot.config import settings


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    storage.reset_schema_cache()


def test_record_feedback_round_trips_through_recent_feedback(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "feedback_db_path", tmp_path / "feedback.db")
    feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "up", "Rome", "https://wiki/Rome")
    rows = feedback.recent_feedback()
    assert len(rows) == 1
    assert rows[0]["user_id"] == "user-1"
    assert rows[0]["game_key"] == "eu4"
    assert rows[0]["vote"] == "up"
    assert rows[0]["top_title"] == "Rome"


def test_recent_feedback_orders_newest_first(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "feedback_db_path", tmp_path / "feedback.db")
    feedback.record_feedback("msg-1", "user-1", "eu4", "first", "up", "A", "u")
    feedback.record_feedback("msg-2", "user-1", "eu4", "second", "down", "B", "u")
    rows = feedback.recent_feedback()
    assert [r["query"] for r in rows] == ["second", "first"]


def test_recent_feedback_respects_limit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "feedback_db_path", tmp_path / "feedback.db")
    for i in range(5):
        feedback.record_feedback(f"msg-{i}", "user-1", "eu4", str(i), "up", "A", "u")
    assert len(feedback.recent_feedback(limit=2)) == 2


def test_recent_feedback_no_table_yet_returns_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "feedback_db_path", tmp_path / "feedback.db")
    assert feedback.recent_feedback() == []


def test_voting_twice_on_one_message_keeps_a_single_row(tmp_path, monkeypatch) -> None:
    """Toggling a reaction off and on must not write a second vote."""
    monkeypatch.setattr(settings, "feedback_db_path", tmp_path / "feedback.db")
    feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "up", "Rome", "u")
    feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "up", "Rome", "u")
    rows = feedback.recent_feedback()
    assert len(rows) == 1


def test_changing_a_vote_replaces_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "feedback_db_path", tmp_path / "feedback.db")
    feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "up", "Rome", "u")
    feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "down", "Rome", "u")
    rows = feedback.recent_feedback()
    assert len(rows) == 1
    assert rows[0]["vote"] == "down"


def test_different_users_vote_independently(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "feedback_db_path", tmp_path / "feedback.db")
    feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "up", "Rome", "u")
    feedback.record_feedback("msg-1", "user-2", "eu4", "rome", "down", "Rome", "u")
    assert len(feedback.recent_feedback()) == 2


def test_different_messages_vote_independently(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "feedback_db_path", tmp_path / "feedback.db")
    feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "up", "Rome", "u")
    feedback.record_feedback("msg-2", "user-1", "eu4", "rome", "up", "Rome", "u")
    assert len(feedback.recent_feedback()) == 2


def _legacy_feedback_db(path: Path) -> None:
    """Write the pre-dedup Feedback table, as it exists on the server today."""
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE Feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                game_key TEXT,
                query TEXT,
                vote TEXT,
                top_title TEXT,
                top_url TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "INSERT INTO Feedback (user_id, game_key, query, vote, top_title, top_url) "
            "VALUES ('user-0', 'eu4', 'old', 'up', 'Old', 'u')"
        )
        conn.commit()
    finally:
        conn.close()


def test_migration_adds_message_id_to_an_existing_database(tmp_path, monkeypatch) -> None:
    db = tmp_path / "feedback.db"
    _legacy_feedback_db(db)
    monkeypatch.setattr(settings, "feedback_db_path", db)

    feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "up", "Rome", "u")

    rows = feedback.recent_feedback()
    assert {r["query"] for r in rows} == {"old", "rome"}


def test_migration_keeps_dedup_working_on_an_existing_database(tmp_path, monkeypatch) -> None:
    db = tmp_path / "feedback.db"
    _legacy_feedback_db(db)
    monkeypatch.setattr(settings, "feedback_db_path", db)

    feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "up", "Rome", "u")
    feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "down", "Rome", "u")

    rows = feedback.recent_feedback()
    assert len(rows) == 2  # the legacy row, plus one deduplicated vote
    assert [r["vote"] for r in rows if r["query"] == "rome"] == ["down"]


def test_migration_is_safe_to_run_against_an_up_to_date_database(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "feedback_db_path", tmp_path / "feedback.db")
    feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "up", "Rome", "u")
    storage.reset_schema_cache()
    feedback.record_feedback("msg-2", "user-1", "eu4", "paris", "up", "Paris", "u")
    assert len(feedback.recent_feedback()) == 2
