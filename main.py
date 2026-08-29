"""Entrypoint: runs the bot and shuts it down cleanly on a signal.

Users run `-eu4 <query>` (and the same for the other games) and get an embed
with the best matching wiki pages. Save files can be pushed to pdx.tools via
`-tools`. Admins get `/admin status` and `/admin feedback`. See paradox_bot/
for the actual implementation.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from paradox_bot import db_migrate, storage
from paradox_bot.bot import ParadoxBot
from paradox_bot.config import settings

logger = logging.getLogger(__name__)


async def run_bot() -> None:
    """Start the bot and close it on SIGINT/SIGTERM.

    `docker stop` sends SIGTERM and waits nine seconds before SIGKILL, and
    deploys restart the container on every merge. Without a handler the process
    dies where it stands. Closing the bot makes `start()` return, and
    `async with` then runs the cleanup — including stopping the health endpoint,
    in ParadoxBot.close().

    Before the gateway comes up the database has to be reachable and migrated:
    the bot can win the startup race against its own Postgres container, so the
    first connection is retried, then Alembic brings the schema up to head.
    """
    storage.init_engine()
    await storage.wait_for_db()
    # Alembic is synchronous and its env.py runs its own event loop, so it must
    # execute off this one.
    await asyncio.to_thread(db_migrate.run_migrations)

    # The seed only loads on a fresh volume. On an existing one the writable
    # tables migrate but the game data may be absent -- warn loudly and let
    # /health stay 503 (it checks the same thing) so a deploy fails rather than
    # shipping a bot whose every search errors on a missing `pages` table.
    if not await storage.game_data_ready():
        logger.critical(
            "The 'pages' table is missing or empty: this volume was never "
            "seeded. The bot will run but /health stays 503 and every search "
            "will fail. Seed the database -- see README -> Дані "
            "(databases/seed.sql.gz, or scripts/import_wiki.py)."
        )

    bot = ParadoxBot()
    loop = asyncio.get_running_loop()

    def request_stop(signal_name: str) -> None:
        logger.info("%s received, shutting down", signal_name)
        loop.create_task(bot.close())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop, sig.name)
        except NotImplementedError:
            # Windows has no add_signal_handler; Ctrl+C still raises
            # KeyboardInterrupt out of asyncio.run, which is good enough for
            # local development. Production is Linux.
            logger.debug("Signal handler for %s unavailable on this platform", sig.name)

    try:
        async with bot:
            await bot.start(settings.token)
    finally:
        await storage.dispose_engine()


def main() -> None:
    if not settings.token:
        logger.critical("TOKEN is not set; copy .env.example to .env and fill it in")
        raise SystemExit(1)

    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down")


if __name__ == "__main__":
    main()
