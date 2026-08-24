"""User-facing string helpers. Ukrainian, by project convention."""

from __future__ import annotations


def pluralize_results(count: int) -> str:
    """Ukrainian plural of 'результат' for the given count."""
    if count % 10 == 1 and count % 100 != 11:
        return "результат"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "результати"
    return "результатів"
