"""Apply Alembic migrations to the writable tables at startup.

The bot upgrades its own schema on boot (see README → Deploy): the home server
runs a single instance, so `alembic upgrade head` on start is simpler than a
separate migration step and cannot drift from the running code.

Alembic is synchronous and its async env.py drives the event loop itself, so
this must run in a worker thread (asyncio.to_thread), never inside the bot's
running loop.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic.command import upgrade
from alembic.config import Config

from paradox_bot.config import settings

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _config() -> Config:
    cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_PROJECT_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


def run_migrations() -> None:
    """Upgrade the database to the latest revision. Blocking; run in a thread."""
    logger.info("Applying database migrations")
    upgrade(_config(), "head")
    logger.info("Database migrations up to date")
