from __future__ import annotations

from paradox_bot.config import Settings, _parse_int


def test_parse_int_valid() -> None:
    assert _parse_int("8080", name="PORT") == 8080


def test_parse_int_empty_returns_none() -> None:
    assert _parse_int("", name="PORT") is None
    assert _parse_int("   ", name="PORT") is None


def test_parse_int_garbage_returns_none() -> None:
    assert _parse_int("not-a-number", name="PORT") is None


def test_settings_from_env_defaults(monkeypatch) -> None:
    for var in (
        "TOKEN",
        "LOG_CHANNEL_ID",
        "BOT_PREFIX",
        "PORT",
        "DEV_GUILD_ID",
        "DAILY_FACT_CHANNEL_ID",
        "PDX_TOOLS_USER_ID",
        "PDX_TOOLS_API_KEY",
        "PDX_TOOLS_API_URL",
        "PDX_TOOLS_SAVE_URL",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings.from_env()

    assert settings.token == ""
    assert settings.log_channel_id is None
    assert settings.bot_prefix == "-"
    assert settings.server_port == 8080
    assert settings.dev_guild_id is None
    assert settings.daily_fact_channel_id is None
    assert settings.pdx_tools_api_url == "https://pdx.tools/api/saves"


def test_settings_from_env_parses_overrides(monkeypatch) -> None:
    monkeypatch.setenv("TOKEN", "abc123")
    monkeypatch.setenv("LOG_CHANNEL_ID", "555")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("DEV_GUILD_ID", "777")
    monkeypatch.setenv("BOT_PREFIX", "!")

    settings = Settings.from_env()

    assert settings.token == "abc123"
    assert settings.log_channel_id == 555
    assert settings.server_port == 9000
    assert settings.dev_guild_id == 777
    assert settings.bot_prefix == "!"


def test_settings_from_env_invalid_port_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "not-a-port")
    settings = Settings.from_env()
    assert settings.server_port == 8080


def test_settings_from_env_parses_daily_fact_channel_id(monkeypatch) -> None:
    monkeypatch.setenv("DAILY_FACT_CHANNEL_ID", "999")
    settings = Settings.from_env()
    assert settings.daily_fact_channel_id == 999
