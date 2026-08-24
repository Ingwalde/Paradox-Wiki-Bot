from __future__ import annotations

from paradox_bot import search_context


def test_remember_stores_by_message_id() -> None:
    search_context.clear()
    search_context.remember(123, game_key="eu4", query="rome", top_title="Rome", top_url="u")
    stored = search_context.get(123)
    assert stored is not None
    assert stored["query"] == "rome"


def test_get_returns_none_for_an_unknown_message() -> None:
    search_context.clear()
    assert search_context.get(999) is None


def test_remember_prunes_oldest_beyond_cap(monkeypatch) -> None:
    search_context.clear()
    monkeypatch.setattr(search_context, "MAX_SEARCH_CONTEXT", 3)
    for message_id in range(5):
        search_context.remember(message_id, game_key="eu4", query=str(message_id))
    # The three most recently added ids survive; the oldest two are pruned.
    assert search_context.get(0) is None
    assert search_context.get(1) is None
    assert [search_context.get(i)["query"] for i in (2, 3, 4)] == ["2", "3", "4"]
