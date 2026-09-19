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
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from config import BOT, API, OWNER, CHANNEL, WEB

pyroutils.MIN_CHAT_ID = -999999999999
pyroutils.MIN_CHANNEL_ID = -10099999999999

logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=WEB.PORT, threaded=True)

BASE_URL = "https://www.1tamilmv.rocks"
FORUM_URL = "https://www.1tamilmv.rocks/index.php?/forums/topic/"
MAX_TOPICS = 15
CHECK_INTERVAL = 300

THUMB_URL = "https://i.ibb.co/bMs3ZWZh/IMG-20260910-232319-421.jpg"
THUMB_PATH = "/tmp/tbl_thumb.jpg"

def download_thumbnail():
    try:
        if os.path.exists(THUMB_PATH) and os.path.getsize(THUMB_PATH) > 0:
            logging.info(f"Thumbnail already exists: {THUMB_PATH}")
            return THUMB_PATH

        logging.info("Downloading Telegram thumbnail...")
        response = requests.get(
            THUMB_URL,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        response.raise_for_status()

        with open(THUMB_PATH, "wb") as file:
            file.write(response.content)

        if not os.path.exists(THUMB_PATH) or os.path.getsize(THUMB_PATH) == 0:
            logging.error("Thumbnail file is empty.")
            return None

        logging.info(f"Thumbnail downloaded successfully: {THUMB_PATH}")
        return THUMB_PATH

    except Exception as e:
        logging.error(f"Failed to download thumbnail: {e}")
        return None

def extract_size(text):
    match = re.search(
        r"(\d+(?:\.\d+)?\s*(?:GB|MB|KB))",
        text,
        re.IGNORECASE
    )
    return match.group(1) if match else "Unknown"

def create_scraper():
    return cloudscraper.create_scraper(
        browser={
            "browser": "chrome",
            "platform": "windows",
            "mobile": False
        }
    )

def crawl_tbl():
    torrents = []
    scraper = create_scraper()

    try:
        logging.info("========================================")
        logging.info("Checking 1TamilMV...")
        logging.info(f"Forum URL: {FORUM_URL}")

        response = scraper.get(
            FORUM_URL,
            timeout=20,
            headers={"Referer": BASE_URL}
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        topic_links = []

        for a in soup.find_all("a", href=True):
            href = a.get("href")
            if not href:
                continue

            href = href.strip()

            if re.search(
                r"index\.php\?/forums/topic/",
                href,
                re.IGNORECASE
            ):
                full_url = urljoin(BASE_URL, href)
                topic_links.append(full_url)

        topic_links = list(dict.fromkeys(topic_links))

        logging.info(f"Found {len(topic_links)} topic links.")

        for topic_url in topic_links[:MAX_TOPICS]:
            try:
                logging.info(f"Checking topic: {topic_url}")

                topic_response = scraper.get(
                    topic_url,
                    timeout=20,
                    headers={"Referer": FORUM_URL}
                )
                topic_response.raise_for_status()

                post_soup = BeautifulSoup(
                    topic_response.text,
                    "html.parser"
                )

                torrent_tags = post_soup.find_all(
                    "a",
                    attrs={"data-fileext": "torrent"}
                )

                file_links = []

                for tag in torrent_tags:
                    href = tag.get("href")

                    if not href:
                        continue

                    href = href.strip()
                    link = urljoin(topic_url, href)

                    raw_text = tag.get_text(
                        " ",
                        strip=True
                    )

                    title = raw_text
                    title = re.sub(
                        r"^www\.\S+\s*-\s*",
                        "",
                        title,
                        flags=re.IGNORECASE
                    ).strip()

                    if title.lower().endswith(".torrent"):
                        title = title[:-8].strip()

                    if not title:
                        title = "1TamilMV Torrent"

                    size = extract_size(raw_text)

                    file_links.append({
                        "type": "torrent",
                        "title": title,
                        "link": link,
                        "size": size
                    })

                if file_links:
                    torrents.append({
                        "topic_url": topic_url,
                        "title": file_links[0]["title"],
                        "size": file_links[0]["size"],
                        "links": file_links
                    })

                    logging.info(
                        f"Found {len(file_links)} torrent file(s)"
                    )

            except Exception as topic_error:
                logging.error(
                    f"Failed to parse topic {topic_url}: "
                    f"{topic_error}"
                )

        logging.info(
            f"1TamilMV crawl completed. "
            f"Topics with torrents: {len(torrents)}"
        )
        logging.info("========================================")

    except Exception as error:
        logging.error(
            f"Failed to fetch 1TamilMV forum: {error}"
        )

    return torrents

class MN_Bot(Client):
    MAX_MSG_LENGTH = 4000

    def __init__(self):
        super().__init__(
            "MN-Bot",
            api_id=API.ID,
            api_hash=API.HASH,
            bot_token=BOT.TOKEN,
            plugins={"root": "plugins"},
            workers=8
        )

        self.channel_id = CHANNEL.ID
        self.last_posted = set()
        self.seen_topics = set()
        self.thumbnail_path = None
        self._crawl_task = None

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

    async def send_torrent(self, file):
        try:
            logging.info(
                f"Downloading torrent: {file['title']}"
            )

            def _download():
                scraper = create_scraper()
                res = scraper.get(
                    file["link"],
                    timeout=30,
                    headers={"Referer": BASE_URL}
                )
                res.raise_for_status()
                return res.content

            content = await asyncio.to_thread(_download)
            file_bytes = io.BytesIO(content)

            # Clean title: strip site-name prefix, illegal filename chars
            clean_title = re.sub(r"^www\.\S+\s*-\s*", "", file["title"], flags=re.IGNORECASE).strip()
            clean_title = re.sub(r'[\\/:*?"<>|]', "_", clean_title)
            clean_title = re.sub(r"\s+", " ", clean_title).strip()

            filename = f"{clean_title.replace(' ', '_')}.torrent"
            file_bytes.name = filename

            caption = (
                f"🎬 <b>{clean_title}</b>\n\n"
                f"📦 <b>Size:</b> {file['size']}\n"
                f"📁 <b>Type:</b> Torrent File\n\n"
                f"#TBL #Torrent"
            )

            thumb = (
                self.thumbnail_path
                if (
                    self.thumbnail_path
                    and os.path.exists(self.thumbnail_path)
                    and os.path.getsize(self.thumbnail_path) > 0
                )
                else None
            )

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if thumb:
                        logging.info(
                            "Sending torrent with thumbnail..."
                        )
                        await self.send_document(
                            self.channel_id,
                            file_bytes,
                            file_name=filename,
                            thumb=thumb,
                            caption=caption,
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        logging.warning(
                            "Thumbnail unavailable. "
                            "Sending without thumbnail."
                        )
                        await self.send_document(
                            self.channel_id,
                            file_bytes,
                            file_name=filename,
                            caption=caption,
                            parse_mode=ParseMode.HTML
                        )

                    logging.info(
                        f"Successfully posted: {file['title']}"
                    )
                    return True

                except FloodWait as e:
                    logging.warning(
                        f"Hit FloodWait! Waiting {e.value}s before retry (attempt {attempt + 1}/{max_retries})..."
                    )
                    await asyncio.sleep(e.value + 2)
                    file_bytes.seek(0)
                except Exception as doc_err:
                    logging.error(
                        f"Failed to send document to Telegram: {doc_err}"
                    )
                    return False

            return False

        except Exception as error:
            logging.error(
                f"Error processing/downloading TBL file "
                f"{file['link']}: {error}"
            )
            return False

    async def auto_post_torrents(self):
        logging.info("Automatic 1TamilMV posting started.")
        is_first_run = True  # Flag to track bot startup

        while True:
            try:
                # Run the blocking network crawler in a worker thread so the MTProto event loop never freezes
                torrents = await asyncio.to_thread(crawl_tbl)

                if not torrents:
                    logging.warning("No torrents returned from 1TamilMV. Will retry on next check interval.")
                else:
                    # Reversing the list posts the newest torrents LAST
                    torrents.reverse()

                    if is_first_run:
                        logging.info("First run detected. Caching current torrents silently to avoid spamming old posts.")

                    for torrent in torrents:
                        topic = torrent["topic_url"]

                        new_files = [
                            file
                            for file in torrent.get("links", [])
                            if file["link"] not in self.last_posted
                        ]

                        if topic in self.seen_topics and not new_files:
                            continue

                        # If this is the bot's first run after a restart, skip sending
                        # and just record the torrents in memory so they aren't sent later.
                        if is_first_run:
                            for file in new_files:
                                self.last_posted.add(file["link"])
                            self.seen_topics.add(topic)
                            continue

                        logging.info(f"Topic: {torrent.get('title', 'Unknown')}")
                        logging.info(f"New torrent files: {len(new_files)}")

                        for file in new_files:
                            success = await self.send_torrent(file)

                            if success:
                                self.last_posted.add(file["link"])
                                await asyncio.sleep(3)

                        self.seen_topics.add(topic)

                    if is_first_run:
                        logging.info("Initial cache complete. The bot will now only post newly added torrents.")
                        is_first_run = False  # Turn off the flag only after successfully caching initial posts

            except asyncio.CancelledError:
                raise
            except Exception as error:
                logging.error(f"Error in auto_post_torrents: {error}", exc_info=True)

            logging.info("Tasks completed. Sleeping while waiting for new torrents...")
            await asyncio.sleep(CHECK_INTERVAL)

    async def _supervisor_loop(self):
        while True:
            try:
                await self.auto_post_torrents()
            except asyncio.CancelledError:
                logging.info("Auto-post supervisor cancelled.")
                break
            except Exception as e:
                logging.error(f"Critical error in auto_post_torrents loop: {e}", exc_info=True)
                logging.info("Supervisor restarting auto_post_torrents in 30 seconds...")
                await asyncio.sleep(30)

    async def start(self):
        await super().start()

        self.thumbnail_path = await asyncio.to_thread(download_thumbnail)

        me = await self.get_me()

        if me.username:
            BOT.USERNAME = f"@{me.username}"
        else:
            BOT.USERNAME = me.first_name

        try:
            await self.send_message(
                OWNER.ID,
                text=(
                    f"{me.first_name} "
                    f"✅ BOT STARTED\n\n"
                    f"📡 Source: 1TamilMV\n"
                    f"🔗 Forum: {FORUM_URL}\n"
                    f"⏱ Check: Every {CHECK_INTERVAL // 60} minutes\n"
                    f"🖼 Thumbnail: "
                    f"{'Enabled' if self.thumbnail_path else 'Disabled'}"
                )
            )
        except Exception as error:
            logging.error(
                f"Could not notify owner: {error}"
            )

        logging.info(
            "MN-Bot started successfully."
        )

        # Retain a strong task reference to prevent Python's garbage collector from destroying it mid-run
        self._crawl_task = asyncio.create_task(
            self._supervisor_loop()
        )

    async def stop(self, *args):
        logging.info(
            "Stopping MN-Bot..."
        )

        if self._crawl_task and not self._crawl_task.done():
            self._crawl_task.cancel()
            try:
                await self._crawl_task
            except asyncio.CancelledError:
                pass

        await super().stop()

        logging.info(
            "MN-Bot stopped."
        )

if __name__ == "__main__":
    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    MN_Bot().run()
