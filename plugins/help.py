import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message

from imgj import INLINE, TEXT

logger = logging.getLogger(__name__)


@Client.on_message(filters.command("help"))
async def help_command(client: Client, msg: Message):
    try:
        await msg.reply_text(
            TEXT.HELP,
            disable_web_page_preview=True,
            reply_markup=INLINE.HELP_BTN,
        )
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            await msg.reply_text(
                TEXT.HELP,
                disable_web_page_preview=True,
                reply_markup=INLINE.HELP_BTN,
            )
        except Exception as retry_err:
            logger.error(f"Failed to reply to /help after FloodWait: {retry_err}")
    except Exception as e:
        logger.error(f"Error handling /help command: {e}")
