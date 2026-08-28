"""Keep-alive/health endpoint, served from the bot's own event loop.

Deliberately not a separate thread with its own server: the Docker health check
polls this endpoint, and a thread would keep answering 200 while the event loop
is wedged — reporting healthy for a bot that has stopped responding to Discord.
Sharing the loop makes an unanswered request mean what the health check assumes
it means.
"""

from __future__ import annotations

import logging

from aiohttp import web

from paradox_bot import storage
from paradox_bot.config import settings

logger = logging.getLogger(__name__)


async def health(request: web.Request) -> web.Response:
    """Liveness plus a cheap database probe.

    The bot is only healthy if it can reach Postgres: with the database down it
    can answer Discord but not actually search or record anything, so a failing
    SELECT 1 turns this red (503) rather than reporting a bot that is only
    half-working as fine.
    """
    logger.debug("Keep-alive ping received")
    if not await storage.check_db():
        return web.Response(status=503, text="database unavailable")
    return web.Response(text="I'm alive!")


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    return app


class KeepAliveServer:
    """Runs the health endpoint alongside the bot, and shuts it down with it."""

    def __init__(self) -> None:
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        runner = web.AppRunner(build_app(), access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=settings.server_port)
        await site.start()
        self._runner = runner
        logger.info("Keep-alive endpoint listening on port %s", settings.server_port)

    async def stop(self) -> None:
        if self._runner is None:
            return
        await self._runner.cleanup()
        self._runner = None
        logger.info("Keep-alive endpoint stopped")
