import logging
import os

from pyrogram import Client, filters
from pyrogram.types import Message

from config import CHANNEL, OWNER

logger = logging.getLogger(__name__)


@Client.on_message(filters.command(["status", "stats"]))
async def status_command(client: Client, msg: Message):
    is_owner = (msg.from_user and msg.from_user.id == OWNER.ID)

    seen_topics_cnt = len(getattr(client, "seen_topics", []))
    last_posted_cnt = len(getattr(client, "last_posted", []))
    thumb_path = getattr(client, "thumbnail_path", None)
    has_thumb = thumb_path and os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0
    crawl_task = getattr(client, "_crawl_task", None)
    is_scraping = bool(crawl_task and not crawl_task.done())

    # Get active base URL
    import bot
    active_domain = getattr(bot, "BASE_URL", "Unknown")

    status_text = (
        "📊 <b>Bot Status & Statistics</b>\n\n"
        f"🤖 <b>Bot:</b> {getattr(client, 'me', client).first_name}\n"
        f"🌐 <b>Active Domain:</b> <code>{active_domain}</code>\n"
        f"📢 <b>Target Channel:</b> <code>{CHANNEL.ID}</code>\n"
        f"🔄 <b>Scraper Active:</b> {'✅ Yes' if is_scraping else '❌ Stopped'}\n"
        f"🖼 <b>Thumbnail:</b> {'✅ Enabled' if has_thumb else '❌ Disabled'}\n"
        f"📑 <b>Seen Topics:</b> <code>{seen_topics_cnt}</code>\n"
        f"🔗 <b>Cached Links:</b> <code>{last_posted_cnt}</code>\n"
    )

    if is_owner:
        status_text += "\n<i>👤 Owner access recognized. Use /check to trigger an immediate crawl.</i>"

    try:
        await msg.reply_text(status_text, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error replying to /status: {e}")
