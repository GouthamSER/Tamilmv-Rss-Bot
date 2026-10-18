from pyrogram import Client as MN_Bot
from pyrogram import filters
from pyrogram.types import Message
from imgj import TEXT, INLINE


@MN_Bot.on_message(filters.command("start"))
async def start(client: MN_Bot, msg: Message):
    await msg.reply_text(
        TEXT.START.format(msg.from_user.mention if msg.from_user else 'there'),
        disable_web_page_preview=True,
        reply_markup=INLINE.START_BTN,
    )

