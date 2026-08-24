from __future__ import annotations

import pytest
from discord.ext import commands

from paradox_bot.bot import ParadoxBot
from paradox_bot.config import settings
from paradox_bot.games import GAMES
from paradox_bot.ui.views import build_links_field


def _page(title: str) -> dict[str, str]:
    return {"title": title, "url": f"https://eu4.paradoxwikis.com/{title}"}


def test_build_links_field_keeps_short_lists_intact() -> None:
    pages = [_page("Ottomans"), _page("Castile"), _page("Ming")]
    assert build_links_field(pages).count("\n") == 2


def test_build_links_field_stays_within_the_embed_limit() -> None:
    # Long mod subpage titles are what push a full result page over the cap.
    pages = [_page("X" * 70) for _ in range(20)]
    assert len(build_links_field(pages)) <= settings.embed_field_limit


def test_build_links_field_drops_only_the_overflow() -> None:
    pages = [_page("X" * 70) for _ in range(20)]
    rendered = build_links_field(pages)
    assert rendered  # not everything is dropped
    assert rendered.count("\n") + 1 < len(pages)


def test_build_links_field_handles_no_results() -> None:
    assert build_links_field([]) == ""


@pytest.fixture()
def bot() -> ParadoxBot:
    return ParadoxBot()


def test_commands_resolve_regardless_of_case(bot: ParadoxBot) -> None:
    for key in GAMES:
        assert bot.get_command(key.upper()) is not None, key


@pytest.mark.parametrize("key", sorted(GAMES))
def test_game_commands_are_rate_limited(bot: ParadoxBot, key: str) -> None:
    cooldown = bot.get_command(key)._buckets._cooldown
    assert cooldown is not None
    assert cooldown.rate == settings.search_cooldown_uses
    assert cooldown.per == settings.search_cooldown_seconds


def test_game_commands_take_the_whole_query(bot: ParadoxBot) -> None:
    # A positional game_key default would let chat text reach db_path().
    for key in GAMES:
        params = bot.get_command(key).clean_params
        assert list(params) == ["query"], key
        assert params["query"].kind is params["query"].kind.KEYWORD_ONLY


def test_max_concurrency_error_is_handled() -> None:
    import inspect

    source = inspect.getsource(ParadoxBot.on_command_error)
    assert commands.MaxConcurrencyReached.__name__ in source
