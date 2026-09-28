from pyrogram import Client as MN_Bot
from pyrogram import filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait
from imgj import TEXT, INLINE
import asyncio


@MN_Bot.on_message(filters.command("start"))
async def start(client: MN_Bot, msg: Message):
    await msg.reply_text(
        TEXT.START.format(msg.from_user.mention),
        disable_web_page_preview=True,
        reply_markup=INLINE.START_BTN,
    )

