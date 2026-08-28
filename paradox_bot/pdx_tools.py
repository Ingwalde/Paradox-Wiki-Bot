"""Upload saves to pdx.tools and remember what we uploaded."""

from __future__ import annotations

import gzip
import json
import logging

import aiohttp
from sqlalchemy import select

from paradox_bot.config import settings
from paradox_bot.storage import Uploads, session

logger = logging.getLogger(__name__)

ZIP_MAGIC = b"PK\x03\x04"
GZIP_MAGIC = b"\x1f\x8b"


class PdxToolsError(Exception):
    """Raised when pdx.tools rejects an upload or replies unexpectedly."""


class PdxDuplicateSaveError(PdxToolsError):
    """Raised when pdx.tools already has this exact save (dedup by content)."""


def _is_duplicate_save_error(body: str) -> bool:
    """Detect pdx.tools' "save already exists" validation error."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    return "already exists" in str(payload.get("msg", "")).lower()


def prepare_save_payload(raw: bytes) -> bytes:
    """Return the save in a form pdx.tools accepts.

    Saves that are already compressed go up untouched; only a plain,
    uncompressed save is gzipped here. Checking for gzip as well as zip
    matters: compressing a .gz upload again produced a gzip stream that
    unpacks into another gzip stream, which is not a save file, and it was
    still sent as Content-Type: application/gzip.
    """
    if raw.startswith(ZIP_MAGIC) or raw.startswith(GZIP_MAGIC):
        return raw
    return gzip.compress(raw)


def _extract_save_url(status: int, body: str) -> str:
    """Turn the API response into a user-facing URL.

    Raises:
        PdxToolsError: If the response carries no recognisable save id.
    """
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PdxToolsError(f"HTTP {status}, відповідь не JSON: {body[:200]}") from exc

    if not isinstance(payload, dict):
        raise PdxToolsError(f"HTTP {status}, несподівана відповідь: {body[:200]}")

    for field in ("save_id", "saveId", "id"):
        save_id = payload.get(field)
        if save_id:
            return settings.pdx_tools_save_url.format(save_id=save_id)

    raise PdxToolsError(f"HTTP {status}, немає ідентифікатора збереження: {body[:200]}")


async def upload_to_pdx_tools(filename: str, payload: bytes) -> str:
    """POST a save to pdx.tools and return its URL.

    The API takes the raw bytes as the body (multipart is not supported), the
    filename in a `pdx-tools-filename` header, and basic auth credentials.

    Raises:
        PdxToolsError: On any non-success response or unreadable payload.
    """
    auth = aiohttp.BasicAuth(settings.pdx_tools_user_id, settings.pdx_tools_api_key)
    timeout = aiohttp.ClientTimeout(total=settings.pdx_tools_timeout_seconds)
    content_type = "application/zip" if payload.startswith(ZIP_MAGIC) else "application/gzip"
    headers = {
        "pdx-tools-filename": filename,
        "Content-Type": content_type,
    }

    try:
        async with (
            aiohttp.ClientSession(timeout=timeout) as session,
            session.post(
                settings.pdx_tools_api_url, data=payload, auth=auth, headers=headers
            ) as response,
        ):
            body = await response.text()
            if response.status >= 400:
                if _is_duplicate_save_error(body):
                    raise PdxDuplicateSaveError(body)
                raise PdxToolsError(f"HTTP {response.status}: {body[:200]}")
            return _extract_save_url(response.status, body)
    except TimeoutError as exc:
        raise PdxToolsError("час очікування відповіді pdx.tools вичерпано") from exc
    except aiohttp.ClientError as exc:
        raise PdxToolsError(f"мережева помилка: {exc}") from exc


async def record_upload(user_id: str, filename: str, url: str) -> None:
    """Persist a successful upload.

    Raises:
        StorageError: If the write fails.
    """
    async with session() as sess:
        sess.add(Uploads(user_id=user_id, filename=filename, url=url))


async def find_prior_upload_url(filename: str) -> str | None:
    """Look up the URL we recorded the last time this filename was uploaded.

    pdx.tools' "save already exists" error carries no save id, so this is how
    the bot recovers the link instead of just saying "already uploaded".

    Raises:
        StorageError: If the read fails.
    """
    stmt = (
        select(Uploads.url)
        .where(Uploads.filename == filename)
        .order_by(Uploads.id.desc())
        .limit(1)
    )
    async with session() as sess:
        return await sess.scalar(stmt)
