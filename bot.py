import asyncio
import io
import logging
import os
import re
import threading
from urllib.parse import urljoin

import requests
from flask import Flask
from bs4 import BeautifulSoup
import cloudscraper

from pyrogram import Client, utils as pyroutils
from config import BOT, API, OWNER, CHANNEL


# ============================================================
# PYROGRAM CHAT ID SETTINGS
# ============================================================

pyroutils.MIN_CHAT_ID = -999999999999
pyroutils.MIN_CHANNEL_ID = -10099999999999


# ============================================================
# LOGGING
# ============================================================

logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)


# ============================================================
# FLASK HEALTH CHECK
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is running!"


def run_flask():
    app.run(
        host="0.0.0.0",
        port=8000,
        threaded=True
    )


# ============================================================
# 1TAMILMV CONFIGURATION
# ============================================================

BASE_URL = "https://www.1tamilmv.rocks"

# Your 1TamilMV forum URL format
FORUM_URL = (
    "https://www.1tamilmv.rocks/"
    "index.php?/forums/topic/"
)

# Number of topics checked every cycle
MAX_TOPICS = 15

# Check interval = 15 minutes
CHECK_INTERVAL = 900


# ============================================================
# THUMBNAIL CONFIGURATION
# ============================================================

THUMB_URL = (
    "https://i.ibb.co/bMs3ZWZh/"
    "IMG-20260910-232319-421.jpg"
)

THUMB_PATH = "/tmp/tbl_thumb.jpg"


# ============================================================
# DOWNLOAD THUMBNAIL
# ============================================================

def download_thumbnail():
    """
    Download remote thumbnail to a local file.

    IMPORTANT:
    Pyrogram expects a local file path for `thumb`.
    It does not directly use an HTTP/HTTPS URL as a file path.
    """

    try:

        # Use existing thumbnail if available
        if (
            os.path.exists(THUMB_PATH)
            and os.path.getsize(THUMB_PATH) > 0
        ):
            logging.info(
                f"Thumbnail already exists: {THUMB_PATH}"
            )
            return THUMB_PATH

        logging.info(
            "Downloading Telegram thumbnail..."
        )

        response = requests.get(
            THUMB_URL,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        response.raise_for_status()

        with open(
            THUMB_PATH,
            "wb"
        ) as file:

            file.write(
                response.content
            )

        # Verify downloaded file
        if (
            not os.path.exists(THUMB_PATH)
            or os.path.getsize(THUMB_PATH) == 0
        ):
            logging.error(
                "Thumbnail file is empty."
            )
            return None

        logging.info(
            f"Thumbnail downloaded successfully: "
            f"{THUMB_PATH}"
        )

        return THUMB_PATH

    except Exception as e:

        logging.error(
            f"Failed to download thumbnail: {e}"
        )

        return None


# ============================================================
# SIZE EXTRACTION
# ============================================================

def extract_size(text):

    match = re.search(
        r"(\d+(?:\.\d+)?\s*(?:GB|MB|KB))",
        text,
        re.IGNORECASE
    )

    return (
        match.group(1)
        if match
        else "Unknown"
    )


# ============================================================
# CREATE CLOUDSCRAPER
# ============================================================

def create_scraper():

    return cloudscraper.create_scraper(
        browser={
            "browser": "chrome",
            "platform": "windows",
            "mobile": False
        }
    )


# ============================================================
# CRAWL 1TAMILMV
# ============================================================

def crawl_tbl():

    torrents = []

    scraper = create_scraper()

    try:

        logging.info(
            "========================================"
        )

        logging.info(
            "Checking 1TamilMV..."
        )

        logging.info(
            f"Forum URL: {FORUM_URL}"
        )

        # ----------------------------------------------------
        # Open forum/topic page
        # ----------------------------------------------------

        response = scraper.get(
            FORUM_URL,
            timeout=20,
            headers={
                "Referer": BASE_URL
            }
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # ----------------------------------------------------
        # Find topic URLs
        #
        # Expected format:
        #
        # /index.php?/forums/topic/123-example/
        #
        # ----------------------------------------------------

        topic_links = []

        for a in soup.find_all(
            "a",
            href=True
        ):

            href = a.get("href")

            if not href:
                continue

            href = href.strip()

            # Match your 1TamilMV URL structure
            if re.search(
                r"index\.php\?/forums/topic/",
                href,
                re.IGNORECASE
            ):

                full_url = urljoin(
                    BASE_URL,
                    href
                )

                topic_links.append(
                    full_url
                )

        # ----------------------------------------------------
        # Remove duplicates while preserving order
        # ----------------------------------------------------

        topic_links = list(
            dict.fromkeys(topic_links)
        )

        logging.info(
            f"Found {len(topic_links)} topic links."
        )

        # ----------------------------------------------------
        # Check first MAX_TOPICS topics
        # ----------------------------------------------------

        for topic_url in topic_links[
            :MAX_TOPICS
        ]:

            try:

                logging.info(
                    f"Checking topic: {topic_url}"
                )

                topic_response = scraper.get(
                    topic_url,
                    timeout=20,
                    headers={
                        "Referer": FORUM_URL
                    }
                )

                topic_response.raise_for_status()

                post_soup = BeautifulSoup(
                    topic_response.text,
                    "html.parser"
                )

                # ------------------------------------------------
                # Find .torrent attachments
                # ------------------------------------------------

                torrent_tags = post_soup.find_all(
                    "a",
                    attrs={
                        "data-fileext": "torrent"
                    }
                )

                file_links = []

                for tag in torrent_tags:

                    href = tag.get("href")

                    if not href:
                        continue

                    href = href.strip()

                    # Convert attachment URL to absolute URL
                    link = urljoin(
                        topic_url,
                        href
                    )

                    raw_text = tag.get_text(
                        " ",
                        strip=True
                    )

                    # ------------------------------------------------
                    # Clean title
                    # ------------------------------------------------

                    title = raw_text.replace(
                        "www.1TamilBlasters.red - ",
                        ""
                    )

                    title = title.strip()

                    # Remove .torrent only from the end
                    if title.lower().endswith(
                        ".torrent"
                    ):
                        title = title[:-8].strip()

                    # If title is empty, use filename fallback
                    if not title:

                        title = (
                            "1TamilMV Torrent"
                        )

                    # ------------------------------------------------
                    # Extract size
                    # ------------------------------------------------

                    size = extract_size(
                        raw_text
                    )

                    file_links.append(
                        {
                            "type": "torrent",
                            "title": title,
                            "link": link,
                            "size": size
                        }
                    )

                # ------------------------------------------------
                # Add topic if torrent files exist
                # ------------------------------------------------

                if file_links:

                    torrents.append(
                        {
                            "topic_url": topic_url,
                            "title": file_links[0][
                                "title"
                            ],
                            "size": file_links[0][
                                "size"
                            ],
                            "links": file_links
                        }
                    )

                    logging.info(
                        f"Found {len(file_links)} "
                        f"torrent file(s)"
                    )

            except Exception as topic_error:

                logging.error(
                    f"Failed to parse topic "
                    f"{topic_url}: "
                    f"{topic_error}"
                )

        logging.info(
            f"1TamilMV crawl completed. "
            f"Topics with torrents: {len(torrents)}"
        )

        logging.info(
            "========================================"
        )

    except Exception as error:

        logging.error(
            f"Failed to fetch 1TamilMV forum: "
            f"{error}"
        )

    return torrents


# ============================================================
# TELEGRAM BOT
# ============================================================

class MN_Bot(Client):

    MAX_MSG_LENGTH = 4000

    def __init__(self):

        super().__init__(
            "MN-Bot",

            api_id=API.ID,

            api_hash=API.HASH,

            bot_token=BOT.TOKEN,

            plugins={
                "root": "plugins"
            },

            workers=8
        )

        self.channel_id = CHANNEL.ID

        # URLs posted during current bot session
        self.last_posted = set()

        # Topics processed during current bot session
        self.seen_topics = set()

        # Local thumbnail path
        self.thumbnail_path = None


    # ========================================================
    # SAFE MESSAGE SENDER
    # ========================================================

    async def safe_send_message(
        self,
        chat_id,
        text,
        **kwargs
    ):

        for i in range(
            0,
            len(text),
            self.MAX_MSG_LENGTH
        ):

            chunk = text[
                i:i + self.MAX_MSG_LENGTH
            ]

            await self.send_message(
                chat_id,
                chunk,
                **kwargs
            )

            await asyncio.sleep(1)


    # ========================================================
    # DOWNLOAD AND SEND TORRENT
    # ========================================================

    async def send_torrent(
        self,
        file
    ):

        try:

            logging.info(
                f"Downloading torrent: "
                f"{file['title']}"
            )

            scraper = create_scraper()

            response = scraper.get(
                file["link"],
                timeout=30,
                headers={
                    "Referer": BASE_URL
                }
            )

            response.raise_for_status()

            # ------------------------------------------------
            # Put torrent into memory
            # ------------------------------------------------

            file_bytes = io.BytesIO(
                response.content
            )

            # ------------------------------------------------
            # Safe Telegram filename
            # ------------------------------------------------

            filename = (
                file["title"]
                .replace(" ", "_")
                .replace("/", "_")
                .replace("\\", "_")
                .replace(":", "_")
                .replace("*", "_")
                .replace("?", "_")
                .replace('"', "_")
                .replace("<", "_")
                .replace(">", "_")
                .replace("|", "_")
                + ".torrent"
            )

            file_bytes.name = filename

            # ------------------------------------------------
            # Caption
            # ------------------------------------------------

            caption = (
                f"{file['title']}\n"
                f"📦 {file['size']}\n"
                f"#tbl #torrent"
            )

            # ------------------------------------------------
            # Check thumbnail
            # ------------------------------------------------

            if (
                self.thumbnail_path
                and os.path.exists(
                    self.thumbnail_path
                )
                and os.path.getsize(
                    self.thumbnail_path
                ) > 0
            ):

                logging.info(
                    "Sending torrent with thumbnail..."
                )

                await self.send_document(
                    self.channel_id,
                    file_bytes,
                    file_name=filename,
                    thumb=self.thumbnail_path,
                    caption=caption
                )

            else:

                logging.warning(
                    "Thumbnail unavailable."
                )

                logging.info(
                    "Sending torrent without thumbnail..."
                )

                await self.send_document(
                    self.channel_id,
                    file_bytes,
                    file_name=filename,
                    caption=caption
                )

            logging.info(
                f"Successfully posted: "
                f"{file['title']}"
            )

            return True

        except Exception as error:

            logging.error(
                f"Error sending TBL file "
                f"{file['link']}: "
                f"{error}"
            )

            return False


    # ========================================================
    # AUTOMATIC TORRENT POSTING
    # ========================================================

    async def auto_post_torrents(self):

        logging.info(
            "Automatic 1TamilMV posting started."
        )

        while True:

            try:

                torrents = crawl_tbl()

                for torrent in torrents:

                    topic = torrent[
                        "topic_url"
                    ]

                    # ----------------------------------------
                    # Find files not posted yet
                    # ----------------------------------------

                    new_files = [
                        file
                        for file in torrent["links"]
                        if file["link"]
                        not in self.last_posted
                    ]

                    # ----------------------------------------
                    # Skip old topic with no new files
                    # ----------------------------------------

                    if (
                        topic in self.seen_topics
                        and not new_files
                    ):

                        continue

                    logging.info(
                        f"Topic: {torrent['title']}"
                    )

                    logging.info(
                        f"New torrent files: "
                        f"{len(new_files)}"
                    )

                    # ----------------------------------------
                    # Send each new torrent
                    # ----------------------------------------

                    for file in new_files:

                        success = (
                            await self.send_torrent(
                                file
                            )
                        )

                        if success:

                            self.last_posted.add(
                                file["link"]
                            )

                            # Wait 3 seconds
                            # between Telegram posts
                            await asyncio.sleep(3)

                    # ----------------------------------------
                    # Mark topic as processed
                    # ----------------------------------------

                    self.seen_topics.add(
                        topic
                    )

            except Exception as error:

                logging.error(
                    f"Error in auto_post_torrents: "
                    f"{error}"
                )

            # ------------------------------------------------
            # Wait 15 minutes
            # ------------------------------------------------

            logging.info(
                "Next 1TamilMV check in "
                "15 minutes..."
            )

            await asyncio.sleep(
                CHECK_INTERVAL
            )


    # ========================================================
    # BOT START
    # ========================================================

    async def start(self):

        await super().start()

        # ----------------------------------------------------
        # Download thumbnail
        # ----------------------------------------------------

        self.thumbnail_path = (
            download_thumbnail()
        )

        # ----------------------------------------------------
        # Get bot information
        # ----------------------------------------------------

        me = await self.get_me()

        if me.username:

            BOT.USERNAME = (
                f"@{me.username}"
            )

        else:

            BOT.USERNAME = (
                me.first_name
            )

        # ----------------------------------------------------
        # Notify owner
        # ----------------------------------------------------

        try:

            await self.send_message(
                OWNER.ID,

                text=(
                    f"{me.first_name} "
                    f"✅ BOT STARTED\n\n"
                    f"📡 Source: 1TamilMV\n"
                    f"🔗 Forum: {FORUM_URL}\n"
                    f"⏱ Check: Every 15 minutes\n"
                    f"🖼 Thumbnail: "
                    f"{'Enabled' if self.thumbnail_path else 'Disabled'}"
                )
            )

        except Exception as error:

            logging.error(
                f"Could not notify owner: "
                f"{error}"
            )

        logging.info(
            "MN-Bot started successfully."
        )

        # ----------------------------------------------------
        # Start automatic crawler
        # ----------------------------------------------------

        asyncio.create_task(
            self.auto_post_torrents()
        )


    # ========================================================
    # BOT STOP
    # ========================================================

    async def stop(self, *args):

        logging.info(
            "Stopping MN-Bot..."
        )

        await super().stop()

        logging.info(
            "MN-Bot stopped."


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    # --------------------------------------------------------
    # Start Flask health check
    # --------------------------------------------------------

    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    # --------------------------------------------------------
    # Start Telegram bot
    # --------------------------------------------------------

    MN_Bot().run()
