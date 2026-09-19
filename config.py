from dotenv import load_dotenv

load_dotenv()  # This will load the variables from .env into os.environ

import os


class BOT:
    """
    TOKEN: Bot token generated from @BotFather
    """
    TOKEN = os.environ.get("TOKEN", "")


class API:
    """
    HASH: Telegram API hash from https://my.telegram.org
    ID = Telegram API ID from https://my.telegram.org
    """
    HASH = os.environ.get("API_HASH", "")
    ID = int(os.environ.get("API_ID", 0))


class OWNER:
    """
    ID: Owner's user id, get it from @userinfobot
    """
    ID = int(os.environ.get("OWNER", 0))


class CHANNEL:
    """
    ID: Telegram Channel ID where the bot will post automatically
    """
    ID = int(os.environ.get("CHANNEL_ID", 0))


class WEB:
    """
    PORT: Specific port no. on which you want to run your bot, DON'T TOUCH IT IF YOU DON'T KNOW WHAT IS IT.
    """
    PORT = int(os.environ.get("PORT", 5000))
