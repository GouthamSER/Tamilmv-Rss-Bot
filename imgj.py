from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from config import OWNER


class TEXT:
    START = """
<b>👋 Hi {}!</b>

I auto-fetch new torrents from <b>1TamilMV</b> and post them to a channel.
No manual work needed.

<b>Developer:</b> @im_goutham_josh
"""
    DEVELOPER = "Developer 💀"
    UPDATES_CHANNEL = "Updates Channel ❣️"
    SOURCE_CODE = "🔗 Source Code"


class INLINE:
    START_BTN = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(TEXT.DEVELOPER, url="https://t.me/im_goutham_josh"),
            ],
            [
                InlineKeyboardButton(
                    TEXT.UPDATES_CHANNEL, url="https://t.me/tamilmvkuttu"
                ),
            ],
            [
                InlineKeyboardButton(
                    TEXT.SOURCE_CODE,
                    url="https://github.com/GouthamSER/Tamilmv-Rss-Bot",
                ),
            ],
        ]
    )
