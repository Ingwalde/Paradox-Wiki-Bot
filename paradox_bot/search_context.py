"""What each search-result message was a search *for*.

Split out of feedback.py: that module persists votes, this one holds the
in-memory correlation the ✅/❌ handler needs to know which query a reaction
refers to. Two different lifetimes -- one survives restarts, one does not.

In-memory and capped on purpose: a reaction on a message from before the last
restart, or older than the cap, is simply not attributable. Persisting it would
mean writing a row for every search on the chance someone reacts.
"""

from __future__ import annotations

from typing import Any

MAX_SEARCH_CONTEXT = 1000
_contexts: dict[int, dict[str, Any]] = {}


def remember(message_id: int, **context: Any) -> None:
    """Record what a search-result message was showing."""
    _contexts[message_id] = context
    while len(_contexts) > MAX_SEARCH_CONTEXT:
        _contexts.pop(next(iter(_contexts)))


def get(message_id: int) -> dict[str, Any] | None:
    """Return the recorded context, or None if it was never stored or aged out."""
    return _contexts.get(message_id)


def clear() -> None:
    """Drop everything. For tests."""
    _contexts.clear()
