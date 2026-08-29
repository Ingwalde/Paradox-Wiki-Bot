"""The -tools command: upload a save file attachment to pdx.tools."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from paradox_bot import metrics
from paradox_bot.config import settings
from paradox_bot.pdx_tools import (
    PdxDuplicateSaveError,
    PdxToolsError,
    find_prior_upload_url,
    prepare_save_payload,
    record_upload,
    upload_to_pdx_tools,
)
from paradox_bot.storage import StorageError

logger = logging.getLogger(__name__)


class ToolsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="tools", help="Завантажити сейв на pdx.tools")
    @commands.max_concurrency(1, commands.BucketType.user)
    @commands.cooldown(
        settings.upload_cooldown_uses,
        settings.upload_cooldown_seconds,
        commands.BucketType.user,
    )
    async def tools(self, ctx: commands.Context) -> None:
        """Take a save file attachment and upload it to pdx.tools."""
        if not (settings.pdx_tools_user_id and settings.pdx_tools_api_key):
            await ctx.send(
                "⚠️ Завантаження на pdx.tools не налаштоване на цьому боті.\n"
                "Ви можете завантажити сейв вручну: <https://pdx.tools>"
            )
            return

        await ctx.send("📤 Завантажте свій сейв-файл для PDX Tools протягом 60 секунд.")

        def check(message: discord.Message) -> bool:
            return (
                message.author == ctx.author
                and message.channel == ctx.channel
                and bool(message.attachments)
            )

        try:
            message = await self.bot.wait_for(
                "message", timeout=settings.upload_wait_seconds, check=check
            )
        except TimeoutError:
            await ctx.send("⏱️ Час очікування вичерпано. Спробуйте ще раз.")
            return

        attachment = message.attachments[0]
        if attachment.size > settings.max_save_bytes:
            limit_mb = settings.max_save_bytes // 1024 // 1024
            await ctx.send(f"❌ Файл завеликий (ліміт {limit_mb} МБ).")
            return

        progress_msg = await ctx.send("⏳ Завантажую на https://pdx.tools")
        try:
            # Read straight into memory: no temp file means no leftover saves on
            # disk and no user-controlled path touching the filesystem.
            raw = await attachment.read()
            payload = await asyncio.to_thread(prepare_save_payload, raw)
            url = await upload_to_pdx_tools(attachment.filename, payload)
        except discord.DiscordException:
            logger.exception("Could not read attachment %s", attachment.filename)
            await ctx.send("❌ Не вдалося прочитати вкладення. Спробуйте ще раз.")
            return
        except PdxDuplicateSaveError:
            metrics.UPLOADS.labels(outcome="duplicate").inc()
            logger.info("Duplicate upload of %s: already on pdx.tools", attachment.filename)
            prior_url = await find_prior_upload_url(attachment.filename)
            if prior_url:
                await ctx.send(f"✅ Завантажено: {prior_url}")
            else:
                await ctx.send(
                    "ℹ️ Цей сейв уже завантажено на pdx.tools раніше.\n"
                    "Знайдіть його тут: <https://pdx.tools/account>"
                )
            return
        except PdxToolsError as exc:
            metrics.UPLOADS.labels(outcome="api_error").inc()
            logger.error("pdx.tools upload failed for %s: %s", attachment.filename, exc)
            await ctx.send(f"❌ pdx.tools відхилив завантаження: {exc}")
            return
        except Exception:
            logger.exception("Unexpected error uploading %s", attachment.filename)
            await ctx.send("❌ Несподівана помилка під час завантаження.")
            return
        finally:
            try:
                await progress_msg.delete()
            except discord.HTTPException:
                logger.warning("Could not delete progress message", exc_info=True)

        metrics.UPLOADS.labels(outcome="success").inc()
        try:
            await record_upload(str(ctx.author.id), attachment.filename, url)
        except StorageError:
            # The upload succeeded; a bookkeeping failure must not hide that.
            metrics.DB_ERRORS.labels(operation="upload").inc()
            logger.exception("Could not record upload of %s", attachment.filename)

        logger.info("uploaded %s for user %s -> %s", attachment.filename, ctx.author.id, url)
        await ctx.send(f"✅ Завантажено: {url}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ToolsCog(bot))
