from __future__ import annotations

from paradox_bot import feedback
from paradox_bot.config import settings


def test_record_feedback_round_trips_through_recent_feedback(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "feedback_db_path", tmp_path / "feedback.db")
    feedback.record_feedback("user-1", "eu4", "rome", "up", "Rome", "https://wiki/Rome")
    rows = feedback.recent_feedback()
    assert len(rows) == 1
    assert rows[0]["user_id"] == "user-1"
    assert rows[0]["game_key"] == "eu4"
    assert rows[0]["vote"] == "up"
    assert rows[0]["top_title"] == "Rome"


def test_recent_feedback_orders_newest_first(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "feedback_db_path", tmp_path / "feedback.db")
    feedback.record_feedback("user-1", "eu4", "first", "up", "A", "u")
    feedback.record_feedback("user-1", "eu4", "second", "down", "B", "u")
    rows = feedback.recent_feedback()
    assert [r["query"] for r in rows] == ["second", "first"]


def test_recent_feedback_respects_limit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "feedback_db_path", tmp_path / "feedback.db")
    for i in range(5):
        feedback.record_feedback("user-1", "eu4", str(i), "up", "A", "u")
    assert len(feedback.recent_feedback(limit=2)) == 2


def test_recent_feedback_no_table_yet_returns_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "feedback_db_path", tmp_path / "feedback.db")
    assert feedback.recent_feedback() == []
