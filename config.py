import os

from dotenv import load_dotenv

load_dotenv()  # Load variables from .env into os.environ


def _get_int(key: str, default: int = 0) -> int:
    """Safely retrieves an integer from environment variables."""
    raw = os.environ.get(key, "")
    if not raw or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except (ValueError, TypeError):
        return default


class BOT:
    """TOKEN: Bot token generated from @BotFather."""
    TOKEN = os.environ.get("TOKEN", "").strip()


class API:
    """
    HASH: Telegram API hash from https://my.telegram.org
    ID: Telegram API ID from https://my.telegram.org
    """
    HASH = os.environ.get("API_HASH", "").strip()
    ID = _get_int("API_ID", 0)


class OWNER:
    """ID: Owner's Telegram user ID, get it from @userinfobot."""
    ID = _get_int("OWNER", 0)


class CHANNEL:
    """ID: Telegram Channel ID where the bot will post automatically."""
    ID = _get_int("CHANNEL_ID", 0)


class WEB:
    """PORT: Port on which the web server will run (default: 5000)."""
    PORT = _get_int("PORT", 5000)


class NETWORK:
    """
    PROXY: Optional HTTP/HTTPS or SOCKS5 proxy (e.g. 'http://127.0.0.1:8080' or 'socks5://127.0.0.1:1080')
    BASE_URL: Custom base URL override (optional, defaults to auto-resolving from WWW.1TAMILMV.FI)
    """
    PROXY = os.environ.get("PROXY", "").strip()
    BASE_URL = os.environ.get("BASE_URL", "").strip()
