from __future__ import annotations

import asyncio
import socket
import urllib.error
import urllib.request

import pytest

from paradox_bot import storage
from paradox_bot.config import settings
from paradox_bot.web import KeepAliveServer, build_app, health


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _fetch(port: int) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
        return str(resp.read().decode())


def _stub_check_db(monkeypatch: pytest.MonkeyPatch, healthy: bool) -> None:
    async def fake_check_db() -> bool:
        return healthy

    monkeypatch.setattr(storage, "check_db", fake_check_db)


def test_app_exposes_the_expected_paths() -> None:
    paths = {route.resource.canonical for route in build_app().router.routes()}
    assert paths == {"/", "/health", "/metrics"}


def test_metrics_endpoint_renders_prometheus_text() -> None:
    from paradox_bot import metrics as metrics_module
    from paradox_bot.web import metrics

    async def run() -> None:
        metrics_module.SEARCHES.labels(game="eu4").inc()
        response = await metrics(None)  # type: ignore[arg-type]
        assert response.status == 200
        assert "text/plain" in response.headers["Content-Type"]
        assert b"paradox_searches_total" in response.body

    asyncio.run(run())


def test_health_returns_the_liveness_string(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_check_db(monkeypatch, healthy=True)

    async def run() -> None:
        response = await health(None)  # type: ignore[arg-type]
        assert response.status == 200
        assert response.text == "I'm alive!"

    asyncio.run(run())


def test_health_is_503_when_the_database_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_check_db(monkeypatch, healthy=False)

    async def run() -> None:
        response = await health(None)  # type: ignore[arg-type]
        assert response.status == 503

    asyncio.run(run())


def test_server_serves_and_then_releases_the_port(monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()
    monkeypatch.setattr(settings, "server_port", port)
    _stub_check_db(monkeypatch, healthy=True)

    async def run() -> None:
        server = KeepAliveServer()
        await server.start()
        try:
            assert await asyncio.to_thread(_fetch, port) == "I'm alive!"
        finally:
            await server.stop()

        # Stopping must actually release the port, or a restart inside the
        # same container would fail to bind.
        with pytest.raises(OSError):
            await asyncio.to_thread(_fetch, port)

    asyncio.run(run())


def test_stop_is_safe_before_start() -> None:
    asyncio.run(KeepAliveServer().stop())


def test_stop_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """close() runs twice on shutdown and stop() must tolerate it.

    The signal handler calls bot.close(), and `async with bot` calls it again
    when start() returns. Both paths reach KeepAliveServer.stop().
    """
    monkeypatch.setattr(settings, "server_port", _free_port())

    async def run() -> None:
        server = KeepAliveServer()
        await server.start()
        await server.stop()
        await server.stop()

    asyncio.run(run())
