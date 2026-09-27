import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.types import Message

from config import OWNER

logger = logging.getLogger(__name__)


@Client.on_message(filters.command(["check", "forcecheck"]))
async def manual_check(client: Client, msg: Message):
    if not msg.from_user or msg.from_user.id != OWNER.ID:
        try:
            await msg.reply_text("⛔ <b>Access Denied:</b> This command is restricted to the bot owner.")
        except Exception as err:
            logger.debug(f"Failed to send access denied: {err}")
        return

    status_msg = await msg.reply_text("🔍 <b>Querying 1TamilMV...</b>\n<i>Please wait while fetching the latest topics.</i>")

    try:
        import bot
        topics = await asyncio.to_thread(bot.crawl_tbl)
        active_domain = getattr(bot, "BASE_URL", "Unknown")

        seen_topics = getattr(client, "seen_topics", set())
        last_posted = getattr(client, "last_posted", set())

        new_count = 0
        for t in topics:
            t_url = t.get("topic_url", "")
            t_rel = t.get("releases", [])
            has_new = False
            for rel in t_rel:
                links = [lnk for lnk in (rel.get("torrent_link"), rel.get("direct_link"), rel.get("magnet")) if lnk]
                if any(link not in last_posted for link in links):
                    has_new = True
                    break
            if t_url not in seen_topics or has_new:
                new_count += 1

        result_text = (
            "✅ <b>1TamilMV Check Complete</b>\n\n"
            f"🌐 <b>Active Domain:</b> <code>{active_domain}</code>\n"
            f"📑 <b>Total Topics Fetched:</b> <code>{len(topics)}</code>\n"
            f"🆕 <b>Unposted / Updated Topics:</b> <code>{new_count}</code>\n\n"
            f"<i>The background scraper will process any new releases automatically.</i>"
        )
        await status_msg.edit_text(result_text, disable_web_page_preview=True)

    except Exception:
        logger.exception("Error during manual check")
        try:
            await status_msg.edit_text("❌ <b>Check Failed</b> - Please check bot logs for details.")
        except Exception as edit_err:
            logger.debug(f"Failed to update status message: {edit_err}")
