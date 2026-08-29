from __future__ import annotations

from paradox_bot import feedback


async def test_record_feedback_round_trips_through_recent_feedback(db: None) -> None:
    await feedback.record_feedback(
        "msg-1", "user-1", "eu4", "rome", "up", "Rome", "https://wiki/Rome"
    )
    rows = await feedback.recent_feedback()
    assert len(rows) == 1
    assert rows[0]["user_id"] == "user-1"
    assert rows[0]["game_key"] == "eu4"
    assert rows[0]["vote"] == "up"
    assert rows[0]["top_title"] == "Rome"


async def test_recent_feedback_orders_newest_first(db: None) -> None:
    await feedback.record_feedback("msg-1", "user-1", "eu4", "first", "up", "A", "u")
    await feedback.record_feedback("msg-2", "user-1", "eu4", "second", "down", "B", "u")
    rows = await feedback.recent_feedback()
    assert [r["query"] for r in rows] == ["second", "first"]


async def test_recent_feedback_respects_limit(db: None) -> None:
    for i in range(5):
        await feedback.record_feedback(f"msg-{i}", "user-1", "eu4", str(i), "up", "A", "u")
    assert len(await feedback.recent_feedback(limit=2)) == 2


async def test_recent_feedback_empty_returns_empty(db: None) -> None:
    assert await feedback.recent_feedback() == []


async def test_voting_twice_on_one_message_keeps_a_single_row(db: None) -> None:
    """Toggling a reaction off and on must not write a second vote."""
    await feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "up", "Rome", "u")
    await feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "up", "Rome", "u")
    rows = await feedback.recent_feedback()
    assert len(rows) == 1


async def test_changing_a_vote_replaces_it(db: None) -> None:
    await feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "up", "Rome", "u")
    await feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "down", "Rome", "u")
    rows = await feedback.recent_feedback()
    assert len(rows) == 1
    assert rows[0]["vote"] == "down"


async def test_different_users_vote_independently(db: None) -> None:
    await feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "up", "Rome", "u")
    await feedback.record_feedback("msg-1", "user-2", "eu4", "rome", "down", "Rome", "u")
    assert len(await feedback.recent_feedback()) == 2


async def test_different_messages_vote_independently(db: None) -> None:
    await feedback.record_feedback("msg-1", "user-1", "eu4", "rome", "up", "Rome", "u")
    await feedback.record_feedback("msg-2", "user-1", "eu4", "rome", "up", "Rome", "u")
    assert len(await feedback.recent_feedback()) == 2
