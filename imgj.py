from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class TEXT:
    START = """<b>👋 Hi {}!</b>

I auto-fetch new torrents from <b>1TamilMV</b> and post them to a channel.
No manual work needed.

<b>Developer:</b> @im_goutham_josh
"""
    HELP = """<b>📖 1TamilMV RSS Bot Help</b>

I automatically monitor 1TamilMV for the latest releases, download .torrent files, and post them with posters, metadata, and direct download links to the configured channel.

<b>Commands:</b>
• /start - Check if bot is alive & view links
• /help - View this help guide
• /status - Check bot runtime stats, cached items & active domain
• /ping - Check bot response speed
• /check - <i>(Owner only)</i> Trigger immediate scrape cycle
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
    HELP_BTN = START_BTN
