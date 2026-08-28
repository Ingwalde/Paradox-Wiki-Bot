"""Logging setup and typed, validated settings loaded once from the environment."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Logging -----------------------------------------------------------------

LOG_DIR = Path("logs")


def setup_logging() -> None:
    """Configure console (INFO) and rotating file (DEBUG) handlers on the root
    logger. Every module then does its own `logging.getLogger(__name__)` and
    inherits these handlers -- keeps log lines attributed to their module and
    lets ruff's BLE001 check recognise `logger.exception(...)` as handling a
    catch-all except, which it can't verify across an imported logger.
    """
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s:%(funcName)s:%(lineno)d %(message)s"
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)

    logfile = RotatingFileHandler(
        LOG_DIR / "bot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    logfile.setLevel(logging.DEBUG)
    logfile.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(logfile)


setup_logging()
logger = logging.getLogger(__name__)


# --- Settings ------------------------------------------------------------


def _parse_int(raw: str, *, name: str) -> int | None:
    """Parse an optional integer env var, logging (not raising) on garbage input."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.error("%s=%r is not a valid integer; ignoring", name, raw)
        return None


def _build_database_url() -> str:
    """Resolve the asyncpg SQLAlchemy URL for the Postgres database.

    An explicit DATABASE_URL wins; otherwise it is assembled from the POSTGRES_*
    parts the official postgres image also reads, so a single .env drives both
    the database container and the bot. The `+asyncpg` driver is forced on so
    every caller gets an async engine regardless of how the URL was supplied.
    """
    explicit = os.getenv("DATABASE_URL", "").strip()
    if explicit:
        # Normalise a bare postg:// or postgresql:// URL onto the async driver.
        for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
            if explicit.startswith(prefix):
                return "postgresql+asyncpg://" + explicit[len(prefix) :]
        return explicit

    host = os.getenv("POSTGRES_HOST", "postgres").strip() or "postgres"
    port = os.getenv("POSTGRES_PORT", "5432").strip() or "5432"
    name = os.getenv("POSTGRES_DB", "paradox").strip() or "paradox"
    user = os.getenv("POSTGRES_USER", "paradox").strip() or "paradox"
    password = os.getenv("POSTGRES_PASSWORD", "").strip()
    credentials = f"{user}:{password}" if password else user
    return f"postgresql+asyncpg://{credentials}@{host}:{port}/{name}"


@dataclass
class Settings:
    """Bot configuration read once from the environment at startup.

    Not frozen: tests monkeypatch individual fields on the single shared
    `settings` instance (e.g. `monkeypatch.setattr(settings, "log_channel_id", x)`).
    Every module reads through that one instance, so the mutation is visible
    everywhere regardless of how each module imported it.
    """

    token: str = ""
    log_channel_id: int | None = None
    bot_prefix: str = "-"
    server_port: int = 8080
    dev_guild_id: int | None = None

    # PostgreSQL connection. Built once from the environment (see
    # _build_database_url); every module reaches the database through the async
    # engine paradox_bot.storage opens from this URL.
    database_url: str = field(default_factory=_build_database_url)
    # Startup can race the database container coming up; retry the first
    # connection this many times with exponential backoff before giving up.
    db_connect_retries: int = 10
    db_connect_base_delay: float = 0.5
    # Upper bound on how long a /health SELECT 1 may take before it is treated
    # as the database being unreachable.
    db_health_timeout_seconds: float = 3.0

    search_result_limit: int = 7
    search_max_results: int = 35
    max_buttons: int = 5
    max_query_length: int = 100

    # Discord rejects an embed field value longer than this.
    embed_field_limit: int = 1024
    # How long the ◀/▶ buttons stay live before they are disabled.
    view_timeout_seconds: float = 300.0
    search_cooldown_uses: int = 4
    search_cooldown_seconds: float = 10.0
    upload_cooldown_uses: int = 1
    upload_cooldown_seconds: float = 60.0

    upload_wait_seconds: float = 60.0
    max_save_bytes: int = 25 * 1024 * 1024

    daily_fact_channel_id: int | None = None

    pdx_tools_user_id: str = ""
    pdx_tools_api_key: str = ""
    pdx_tools_api_url: str = "https://pdx.tools/api/saves"
    # Confirmed against https://pdx.tools/docs/api/: the docs' only worked
    # example is EU4 ("hosted at /eu4/saves/xxx"); other games are undocumented.
    pdx_tools_save_url: str = "https://pdx.tools/eu4/saves/{save_id}"
    pdx_tools_timeout_seconds: int = 300

    @classmethod
    def from_env(cls) -> Settings:
        port = _parse_int(os.getenv("PORT", ""), name="PORT")
        log_channel_id = _parse_int(os.getenv("LOG_CHANNEL_ID", ""), name="LOG_CHANNEL_ID")
        if log_channel_id is None:
            logger.warning("LOG_CHANNEL_ID is not set; search requests will not be mirrored")
        dev_guild_id = _parse_int(os.getenv("DEV_GUILD_ID", ""), name="DEV_GUILD_ID")
        daily_fact_channel_id = _parse_int(
            os.getenv("DAILY_FACT_CHANNEL_ID", ""), name="DAILY_FACT_CHANNEL_ID"
        )

        return cls(
            token=os.getenv("TOKEN", "").strip(),
            log_channel_id=log_channel_id,
            database_url=_build_database_url(),
            bot_prefix=os.getenv("BOT_PREFIX", "-"),
            server_port=port if port is not None else 8080,
            dev_guild_id=dev_guild_id,
            daily_fact_channel_id=daily_fact_channel_id,
            pdx_tools_user_id=os.getenv("PDX_TOOLS_USER_ID", "").strip(),
            pdx_tools_api_key=os.getenv("PDX_TOOLS_API_KEY", "").strip(),
            pdx_tools_api_url=os.getenv(
                "PDX_TOOLS_API_URL", "https://pdx.tools/api/saves"
            ).strip(),
            pdx_tools_save_url=os.getenv(
                "PDX_TOOLS_SAVE_URL", "https://pdx.tools/eu4/saves/{save_id}"
            ).strip(),
        )


settings = Settings.from_env()
