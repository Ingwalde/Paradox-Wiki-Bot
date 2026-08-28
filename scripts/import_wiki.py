"""Populate a game's rows in Postgres from its paradoxwikis.com MediaWiki API.

No API key needed; the database URL comes from the environment (see
paradox_bot.config). Usage:

    python scripts/import_wiki.py eu5

Replaces the game's rows in the shared `pages` and `redirects` tables (one
DELETE + insert per game, in a single transaction), so it is safe to re-run and
always reflects current wiki state. To regenerate the committed seed dump
afterwards, run scripts/dump_seed.py.

To add a new game: add it to GAMES in paradox_bot/games.py (with its
wiki_subdomain), then run this script.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from sqlalchemy import delete, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paradox_bot import storage
from paradox_bot.games import GAMES

USER_AGENT = "paradox-discord-bot-wiki-import/1.0"
REQUEST_DELAY_SECONDS = 0.2
# Characters MediaWiki leaves literal in page URLs (observed in existing
# databases, e.g. "Holy_Roman_Empire_(mechanic)"); everything else is
# percent-encoded so titles with &, #, % etc. don't break the URL.
URL_SAFE_CHARS = "()_,'!.-/:"


def _api_get(subdomain: str, params: dict) -> dict:
    url = f"https://{subdomain}.paradoxwikis.com/api.php?" + urllib.parse.urlencode(
        {**params, "format": "json"}
    )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _page_url(subdomain: str, title: str, fragment: str = "") -> str:
    path = urllib.parse.quote(title.replace(" ", "_"), safe=URL_SAFE_CHARS)
    url = f"https://{subdomain}.paradoxwikis.com/{path}"
    if fragment:
        url += "#" + urllib.parse.quote(fragment.replace(" ", "_"), safe=URL_SAFE_CHARS)
    return url


def _redirect_index_url(subdomain: str, title: str) -> str:
    encoded_title = urllib.parse.quote(title.replace(" ", "_"), safe=URL_SAFE_CHARS)
    return f"https://{subdomain}.paradoxwikis.com/index.php?title={encoded_title}&redirect=no"


def fetch_pages(subdomain: str) -> list[tuple[str, str, str]]:
    """Return (title, url, image_url) for every non-redirect content page."""
    pages: list[tuple[str, str, str]] = []
    params: dict = {
        "action": "query",
        "generator": "allpages",
        "gapfilterredir": "nonredirects",
        "gaplimit": "500",
        "prop": "pageimages",
        "piprop": "original",
    }
    while True:
        data = _api_get(subdomain, params)
        for page in data.get("query", {}).get("pages", {}).values():
            title = page["title"]
            image = page.get("original", {}).get("source", "")
            pages.append((title, _page_url(subdomain, title), image))
        cont = data.get("continue")
        if not cont:
            break
        params.update(cont)
        time.sleep(REQUEST_DELAY_SECONDS)
    return pages


def fetch_redirects(subdomain: str) -> list[tuple[str, str, str]]:
    """Return (redirect_title, redirect_url, target_page_url) for every redirect.

    list=allredirects gives the redirect's own page id ("fromid") and its
    TARGET title/fragment -- not the redirect's own title -- so a second,
    batched query resolves those ids back to titles.
    """
    raw: list[tuple[int, str, str]] = []  # (fromid, target_title, fragment)
    params: dict = {
        "action": "query",
        "list": "allredirects",
        "arlimit": "500",
        "arprop": "ids|title|fragment",
    }
    while True:
        data = _api_get(subdomain, params)
        for entry in data.get("query", {}).get("allredirects", []):
            raw.append((entry["fromid"], entry["title"], entry.get("fragment", "")))
        cont = data.get("continue")
        if not cont:
            break
        params.update(cont)
        time.sleep(REQUEST_DELAY_SECONDS)

    titles_by_id: dict[int, str] = {}
    ids = [fromid for fromid, _, _ in raw]
    for i in range(0, len(ids), 50):
        chunk = ids[i : i + 50]
        data = _api_get(
            subdomain, {"action": "query", "pageids": "|".join(str(x) for x in chunk)}
        )
        for page in data.get("query", {}).get("pages", {}).values():
            if "missing" not in page:
                titles_by_id[page["pageid"]] = page["title"]
        time.sleep(REQUEST_DELAY_SECONDS)

    redirects = []
    for fromid, target_title, fragment in raw:
        redirect_title = titles_by_id.get(fromid)
        if redirect_title is None:
            continue
        redirects.append(
            (
                redirect_title,
                _redirect_index_url(subdomain, redirect_title),
                _page_url(subdomain, target_title, fragment),
            )
        )
    return redirects


async def _write_async(
    game_key: str,
    pages: list[tuple[str, str, str]],
    redirects: list[tuple[str, str, str]],
) -> None:
    """Replace one game's rows atomically: DELETE then bulk INSERT.

    Idempotent per game (the SQLite version dropped and recreated the whole
    file; the shared tables here can only clear the one game's rows). Duplicate
    titles/urls within a game are ignored, matching the old INSERT OR IGNORE.
    """
    storage.init_engine()
    try:
        async with storage.session() as sess:
            await sess.execute(delete(storage.Pages).where(storage.Pages.game_key == game_key))
            await sess.execute(
                delete(storage.Redirects).where(storage.Redirects.game_key == game_key)
            )
            if pages:
                await sess.execute(
                    pg_insert(storage.Pages).on_conflict_do_nothing(),
                    [
                        {"game_key": game_key, "title": t, "url": u, "image_url": i}
                        for t, u, i in pages
                    ],
                )
            if redirects:
                await sess.execute(
                    insert(storage.Redirects),
                    [
                        {
                            "game_key": game_key,
                            "redirect_title": rt,
                            "redirect_url": ru,
                            "target_page_url": tp,
                        }
                        for rt, ru, tp in redirects
                    ],
                )
    finally:
        await storage.dispose_engine()


def write_database(
    game_key: str,
    pages: list[tuple[str, str, str]],
    redirects: list[tuple[str, str, str]],
) -> None:
    asyncio.run(_write_async(game_key, pages, redirects))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_key", choices=sorted(GAMES))
    args = parser.parse_args()

    subdomain = GAMES[args.game_key].wiki_subdomain
    print(f"Fetching pages from {subdomain}.paradoxwikis.com ...")
    pages = fetch_pages(subdomain)
    print(f"  {len(pages)} pages")
    print(f"Fetching redirects from {subdomain}.paradoxwikis.com ...")
    redirects = fetch_redirects(subdomain)
    print(f"  {len(redirects)} redirects")

    write_database(args.game_key, pages, redirects)
    print(f"Wrote {len(pages)} pages and {len(redirects)} redirects for {args.game_key}")


if __name__ == "__main__":
    main()
