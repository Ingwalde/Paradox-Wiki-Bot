"""Discord views and the embed pieces they own.

Presentation only: no database access, no bot instance, no event handling.
`discord.Embed` and `discord.ui.View` construct fine without a gateway
connection, which is why this layer is directly unit-tested.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import discord
from discord import ui

from paradox_bot.config import settings
from paradox_bot.games import GameInfo
from paradox_bot.ui.text import pluralize_results

logger = logging.getLogger(__name__)

def build_links_field(pages: Iterable[dict[str, Any]]) -> str:
    """Render result links, dropping any that would overflow the field limit.

    Long mod subpage titles can push a full page of results past Discord's
    1024-character field cap, which would fail the whole message with 400.
    """
    lines: list[str] = []
    used = 0
    for page in pages:
        line = f"[{page['title']}]({page['url']})"
        cost = len(line) + (1 if lines else 0)  # the newline that joins it
        if used + cost > settings.embed_field_limit:
            break
        lines.append(line)
        used += cost
    return "\n".join(lines)


class LinksView(ui.View):
    """Row of link buttons for a short, non-paginated list (fuzzy suggestions)."""

    def __init__(self, pages: Iterable[dict[str, Any]]) -> None:
        super().__init__(timeout=None)
        for page in list(pages)[: settings.max_buttons]:
            # Discord rejects button labels longer than 80 characters.
            self.add_item(ui.Button(label=page["title"][:80], url=page["url"]))


class _NavButton(ui.Button):
    """A ◀/▶ button whose click runs the given async callback.

    Overriding callback() as a real method, rather than assigning a function
    to button.callback after construction, is what mypy can actually verify
    against discord.py's Item.callback signature.
    """

    def __init__(
        self,
        *,
        label: str,
        disabled: bool,
        on_click: Callable[[discord.Interaction], Awaitable[None]],
    ) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary, disabled=disabled)
        self._on_click = on_click

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._on_click(interaction)


class PaginatedResultsView(ui.View):
    """Search results: direct link buttons for the current page, plus ◀/▶
    navigation once there's more than one page (fetched up to
    settings.search_max_results, settings.search_result_limit per page).
    """

    def __init__(self, pages: list[dict[str, Any]], game: GameInfo, author_id: int) -> None:
        super().__init__(timeout=settings.view_timeout_seconds)
        self.pages = pages
        self.game = game
        self.author_id = author_id
        self.page_size = settings.search_result_limit
        self.index = 0
        # Set by send_wiki_embed once the message exists, so on_timeout can
        # edit the buttons out. None if sending failed.
        self.message: discord.Message | None = None
        self._render()

    @property
    def total_pages(self) -> int:
        return (len(self.pages) - 1) // self.page_size + 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only whoever ran the search may page through it.

        Without this, anyone in the channel can advance someone else's results
        and the message changes under them.
        """
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "↔️ Це чужий пошук. Запустіть власний, щоб гортати.", ephemeral=True
        )
        return False

    async def on_timeout(self) -> None:
        """Disable the buttons rather than leave them looking clickable.

        Discord does not retire a view's components on its own: after the
        timeout they still render enabled and a click answers "interaction
        failed".
        """
        for item in self.children:
            if isinstance(item, ui.Button) and item.url is None:
                item.disabled = True
        if self.message is None:
            return
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            # Message deleted, or we lost access to the channel. Nothing to fix.
            logger.debug("Could not disable timed-out view", exc_info=True)

    def _current_slice(self) -> list[dict[str, Any]]:
        start = self.index * self.page_size
        return self.pages[start : start + self.page_size]

    def _render(self) -> None:
        self.clear_items()
        for page in self._current_slice()[: settings.max_buttons]:
            self.add_item(ui.Button(label=page["title"][:80], url=page["url"]))
        if self.total_pages > 1:
            self.add_item(
                _NavButton(label="◀", disabled=self.index == 0, on_click=self._go_prev)
            )
            self.add_item(
                _NavButton(
                    label="▶",
                    disabled=self.index >= self.total_pages - 1,
                    on_click=self._go_next,
                )
            )

    def build_embed(self) -> discord.Embed:
        chunk = self._current_slice()
        embed = discord.Embed(title=chunk[0]["title"], url=chunk[0]["url"], color=self.game.color)
        embed.set_thumbnail(url=self.game.logo)
        if chunk[0].get("image_url"):
            embed.set_image(url=chunk[0]["image_url"])
        # The top result of the page is already the embed title/link; listing
        # it again here would be the third copy of the same link.
        rest = chunk[1:]
        if rest:
            links_text = build_links_field(rest)
            if links_text:
                embed.add_field(name="🔗 Ще результати", value=links_text, inline=False)
        page_note = (
            f" · стор. {self.index + 1}/{self.total_pages}" if self.total_pages > 1 else ""
        )
        embed.set_footer(
            text=f"{self.game.name} Wiki · {len(self.pages)} "
            f"{pluralize_results(len(self.pages))}{page_note}"
        )
        return embed

    async def _go_prev(self, interaction: discord.Interaction) -> None:
        self.index = max(0, self.index - 1)
        self._render()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _go_next(self, interaction: discord.Interaction) -> None:
        self.index = min(self.total_pages - 1, self.index + 1)
        self._render()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

