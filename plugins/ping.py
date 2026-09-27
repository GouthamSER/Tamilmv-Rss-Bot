import logging
import time

from pyrogram import Client, filters
from pyrogram.types import Message

logger = logging.getLogger(__name__)


@Client.on_message(filters.command("ping"))
async def ping(client: Client, msg: Message):
    start_time = time.monotonic()
    reply = await msg.reply_text("🏓 <i>Pinging...</i>")
    latency = round((time.monotonic() - start_time) * 1000)
    try:
        await reply.edit_text(f"🏓 <b>Pong!</b> <code>{latency}ms</code>")
    except Exception as e:
        logger.error(f"Error editing ping message: {e}")
