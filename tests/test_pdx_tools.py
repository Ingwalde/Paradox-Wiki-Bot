from __future__ import annotations

import asyncio
import base64
import gzip

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from paradox_bot import pdx_tools
from paradox_bot.config import settings


def test_find_prior_upload_url_returns_most_recent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "upload_db_path", tmp_path / "pdx_tools.db")
    pdx_tools.record_upload("user-1", "save.eu4", "https://pdx.tools/eu4/saves/old")
    pdx_tools.record_upload("user-1", "save.eu4", "https://pdx.tools/eu4/saves/new")
    assert pdx_tools.find_prior_upload_url("save.eu4") == "https://pdx.tools/eu4/saves/new"


def test_find_prior_upload_url_unknown_filename_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "upload_db_path", tmp_path / "pdx_tools.db")
    pdx_tools.record_upload("user-1", "save.eu4", "https://pdx.tools/eu4/saves/old")
    assert pdx_tools.find_prior_upload_url("other.eu4") is None


def test_find_prior_upload_url_no_table_yet_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "upload_db_path", tmp_path / "pdx_tools.db")
    assert pdx_tools.find_prior_upload_url("save.eu4") is None


def test_prepare_save_payload_passes_zip_through() -> None:
    raw = pdx_tools.ZIP_MAGIC + b"rest of a zip file"
    assert pdx_tools.prepare_save_payload(raw) == raw


def test_prepare_save_payload_gzips_non_zip() -> None:
    raw = b"plain text save, not a zip"
    payload = pdx_tools.prepare_save_payload(raw)
    assert payload != raw
    assert gzip.decompress(payload) == raw


def test_prepare_save_payload_passes_gzip_through() -> None:
    """An already-gzipped upload must not be gzipped a second time.

    Compressing it again yielded a stream that unpacks into another gzip
    stream rather than into the save, which pdx.tools cannot read.
    """
    save = b"plain text save, not a zip"
    raw = gzip.compress(save)
    assert pdx_tools.prepare_save_payload(raw) == raw
    assert gzip.decompress(pdx_tools.prepare_save_payload(raw)) == save


def test_extract_save_url_valid_json() -> None:
    url = pdx_tools._extract_save_url(200, '{"save_id": "abc123"}')
    assert url == settings.pdx_tools_save_url.format(save_id="abc123")


@pytest.mark.parametrize("field", ["save_id", "saveId", "id"])
def test_extract_save_url_accepts_known_fields(field: str) -> None:
    url = pdx_tools._extract_save_url(200, f'{{"{field}": "xyz"}}')
    assert url == settings.pdx_tools_save_url.format(save_id="xyz")


def test_extract_save_url_non_json_raises() -> None:
    with pytest.raises(pdx_tools.PdxToolsError):
        pdx_tools._extract_save_url(502, "<html>Bad Gateway</html>")


def test_extract_save_url_json_without_id_raises() -> None:
    with pytest.raises(pdx_tools.PdxToolsError):
        pdx_tools._extract_save_url(200, '{"msg": "not enough save slots"}')


def test_upload_to_pdx_tools_sends_auth_header_filename_and_body(monkeypatch) -> None:
    seen: dict = {}

    async def handler(request: web.Request) -> web.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["filename"] = request.headers.get("pdx-tools-filename")
        seen["content_type"] = request.headers.get("Content-Type")
        seen["body"] = await request.read()
        return web.json_response({"save_id": "server-id"})

    async def run() -> str:
        app = web.Application()
        app.router.add_post("/api/saves", handler)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            monkeypatch.setattr(settings, "pdx_tools_api_url", str(client.make_url("/api/saves")))
            monkeypatch.setattr(settings, "pdx_tools_user_id", "user-42")
            monkeypatch.setattr(settings, "pdx_tools_api_key", "secret-key")
            payload = pdx_tools.ZIP_MAGIC + b"payload bytes"
            return await pdx_tools.upload_to_pdx_tools("game.eu4", payload)
        finally:
            await client.close()

    url = asyncio.run(run())

    assert url == settings.pdx_tools_save_url.format(save_id="server-id")
    assert seen["filename"] == "game.eu4"
    assert seen["content_type"] == "application/zip"
    assert seen["body"] == pdx_tools.ZIP_MAGIC + b"payload bytes"

    expected_auth = "Basic " + base64.b64encode(b"user-42:secret-key").decode()
    assert seen["auth"] == expected_auth


def test_upload_to_pdx_tools_raises_duplicate_error(monkeypatch) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response(
            {"name": "ValidationError", "msg": "save already exists"}, status=400
        )

    async def run() -> None:
        app = web.Application()
        app.router.add_post("/api/saves", handler)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            monkeypatch.setattr(settings, "pdx_tools_api_url", str(client.make_url("/api/saves")))
            monkeypatch.setattr(settings, "pdx_tools_user_id", "user-42")
            monkeypatch.setattr(settings, "pdx_tools_api_key", "secret-key")
            with pytest.raises(pdx_tools.PdxDuplicateSaveError):
                await pdx_tools.upload_to_pdx_tools("game.eu4", b"data")
        finally:
            await client.close()

    asyncio.run(run())


def test_upload_to_pdx_tools_raises_on_http_error(monkeypatch) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"msg": "no slots"}, status=400)

    async def run() -> None:
        app = web.Application()
        app.router.add_post("/api/saves", handler)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            monkeypatch.setattr(settings, "pdx_tools_api_url", str(client.make_url("/api/saves")))
            monkeypatch.setattr(settings, "pdx_tools_user_id", "user-42")
            monkeypatch.setattr(settings, "pdx_tools_api_key", "secret-key")
            with pytest.raises(pdx_tools.PdxToolsError):
                await pdx_tools.upload_to_pdx_tools("game.eu4", b"data")
        finally:
            await client.close()

    asyncio.run(run())
