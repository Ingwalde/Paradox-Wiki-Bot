from __future__ import annotations

import pytest

from paradox_bot.ui.text import pluralize_results


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, "результат"),
        (21, "результат"),
        (2, "результати"),
        (3, "результати"),
        (4, "результати"),
        (22, "результати"),
        (5, "результатів"),
        (0, "результатів"),
        (11, "результатів"),
        (12, "результатів"),
        (14, "результатів"),
        (111, "результатів"),
    ],
)
def test_pluralize_results(count: int, expected: str) -> None:
    assert pluralize_results(count) == expected
