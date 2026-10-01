import asyncio
import io
import logging
import os
import re
import tempfile
import threading
from html import escape
from urllib.parse import urljoin, urlparse

import requests
from flask import Flask
from bs4 import BeautifulSoup

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

from pyrogram import Client, utils as pyroutils
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from config import BOT, API, OWNER, CHANNEL, WEB, NETWORK, LIMITS
from plugins.db import StateDB

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


GATEWAY_DOMAINS = [
    "https://www.1tamilmv.fi",
    "https://1tamilmv.fi",
    "https://www.1tamilmv.rocks",
]

BASE_URL = NETWORK.BASE_URL.rstrip("/") if NETWORK.BASE_URL else "https://www.1tamilmv.rocks"
FORUM_URL = f"{BASE_URL}/index.php?/forums/topic/"

MAX_TOPICS = 13
CHECK_INTERVAL = 600

THUMB_URL = os.getenv("THUMB_URL") or "https://i.ibb.co/DPrwsGsC/IMG-20260919-174828-023.jpg"
THUMB_PATH = os.path.join(tempfile.gettempdir(), "tbl_thumb.jpg")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _set_base(url):
    global BASE_URL, FORUM_URL
    BASE_URL = url
    FORUM_URL = f"{BASE_URL}/index.php?/forums/topic/"
    return BASE_URL


def create_scraper():
    if HAS_CLOUDSCRAPER:
        try:
            s = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
            if NETWORK.PROXY:
                s.proxies = {"http": NETWORK.PROXY, "https": NETWORK.PROXY}
            return s
        except Exception as error:
            logging.warning(f"Could not create Cloudscraper session: {error}")

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if NETWORK.PROXY:
        session.proxies = {"http": NETWORK.PROXY, "https": NETWORK.PROXY}
    return session


def discover_active_domain():
    """Follow gateway redirects or read the site banner to find the active domain."""
    if NETWORK.BASE_URL:
        return _set_base(NETWORK.BASE_URL.rstrip("/"))

    scraper = create_scraper()

    # 1. Permanent redirect gateways
    for gateway in ["https://www.1tamilmv.fi", "https://1tamilmv.fi"]:
        try:
            r = scraper.get(gateway, timeout=8, allow_redirects=False)
            if r.status_code in (301, 302, 307, 308) and r.headers.get("Location"):
                p = urlparse(r.headers["Location"])
                final = f"{p.scheme}://{p.netloc}".rstrip("/")
                if "tamilmv" in final.lower():
                    logging.info(f"Gateway {gateway} redirected to active domain: {final}")
                    return _set_base(final)
        except Exception as error:
            logging.debug(f"Gateway check failed for {gateway}: {error}")

    # 2. Known domains
    for domain in GATEWAY_DOMAINS:
        try:
            r = scraper.get(domain, timeout=10, allow_redirects=True)
            if r.status_code == 200:
                m = re.search(
                    r"official\s+website\s+(WWW\.[A-Z0-9.-]+)", r.text, re.IGNORECASE
                )
                if m:
                    official = f"https://{m.group(1).lower()}".rstrip("/")
                    logging.info(f"Official domain discovered from site banner: {official}")
                    return _set_base(official)

                p = urlparse(r.url)
                return _set_base(f"{p.scheme}://{p.netloc}".rstrip("/"))
        except Exception as error:
            logging.debug(f"Known domain check failed for {domain}: {error}")

    return BASE_URL


def download_thumbnail():
    try:
        if os.path.exists(THUMB_PATH) and os.path.getsize(THUMB_PATH) > 0:
            logging.info(f"Thumbnail already exists: {THUMB_PATH}")
            return THUMB_PATH

        logging.info("Downloading Telegram thumbnail...")
        r = create_scraper().get(
            THUMB_URL, timeout=20, headers={"User-Agent": DEFAULT_HEADERS["User-Agent"]}
        )
        r.raise_for_status()

        with open(THUMB_PATH, "wb") as f:
            f.write(r.content)

        if not os.path.exists(THUMB_PATH) or os.path.getsize(THUMB_PATH) == 0:
            logging.error("Thumbnail file is empty.")
            return None

        logging.info(f"Thumbnail downloaded successfully: {THUMB_PATH}")
        return THUMB_PATH

    except Exception as error:
        logging.error(f"Failed to download thumbnail: {error}")
        return None


def sync_thumbnail(db):
    """
    Thumbnail image lives in the DB. Local file is only a cache for Pyrogram.
    - Same URL + file on disk      -> reuse.
    - Same URL + file missing      -> restore from DB (no web download).
    - URL changed / nothing in DB  -> delete old file, download new, replace in DB.
    Bytes are never kept in memory after this function returns.
    """
    stored_url = db.get_thumb_url()
    has_file = os.path.exists(THUMB_PATH) and os.path.getsize(THUMB_PATH) > 0

    if stored_url == THUMB_URL:
        if has_file:
            logging.info("Thumbnail unchanged, using existing file.")
            return THUMB_PATH

        data = db.get_thumb_data()
        if data:
            with open(THUMB_PATH, "wb") as f:
                f.write(data)
            del data
            logging.info("Thumbnail restored from DB.")
            return THUMB_PATH

    if os.path.exists(THUMB_PATH):
        try:
            os.remove(THUMB_PATH)
            logging.info("Old thumbnail deleted.")
        except Exception as error:
            logging.warning(f"Could not delete old thumbnail: {error}")

    path = download_thumbnail()
    if path:
        with open(path, "rb") as f:
            db.set_thumb(THUMB_URL, f.read())
    return path


def download_image(url, referer=None):
    try:
        headers = dict(DEFAULT_HEADERS)
        if referer:
            headers["Referer"] = referer

        r = create_scraper().get(url, timeout=25, headers=headers)
        r.raise_for_status()

        if r.content:
            return r.content
    except Exception as error:
        logging.warning(f"Failed to download image from {url}: {error}")
    return None


def extract_size(text):
    m = re.search(r"(\d+(?:\.\d+)?\s*(?:GB|MB|KB))", text, re.IGNORECASE)
    return m.group(1) if m else "Unknown"


def clean_release_title(raw_title):
    title = re.sub(r"^www\.\S+\s*-\s*", "", raw_title.strip(), flags=re.IGNORECASE).strip()

    if title.lower().endswith(".torrent"):
        title = title[:-8].strip()
    if title.lower().endswith(".mkv"):
        title = title[:-4].strip()

    return re.sub(r"\s+", " ", title).strip() or "1TamilMV Release"


BAD_IMG_WORDS = [
    "smilies", "border", "utorrent", "torrborder",
    "default_large", "theme", "icon", "blank.gif",
]


def parse_topic(scraper, topic_url):
    """Fetch one topic page. Returns topic dict or None."""
    logging.info(f"Checking topic: {topic_url}")

    r = scraper.get(topic_url, timeout=20, headers={"Referer": FORUM_URL})
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    post = (
        soup.find("div", attrs={"data-role": "commentContent"})
        or soup.find("div", class_="cPost_contentWrap")
    )
    if not post:
        return None

    # Poster image
    poster_url = None
    for img in post.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        if any(bad in src.lower() for bad in BAD_IMG_WORDS):
            continue
        poster_url = urljoin(topic_url, src)
        break

    # Releases
    releases = []
    current = None

    for a in post.find_all("a"):
        href = a.get("href", "").strip()
        href_lower = href.lower()
        fileext = a.get("data-fileext")
        raw_text = a.get_text(" ", strip=True)

        is_torrent = (
            (fileext and fileext.lower() == "torrent")
            or ("attachment.php" in href_lower and "key=" in href_lower)
            or href_lower.endswith(".torrent")
        )

        if is_torrent:
            current = {
                "title": clean_release_title(raw_text),
                "torrent_link": urljoin(topic_url, href),
                "size": extract_size(raw_text),
                "direct_link": None,
                "magnet": None,
            }
            releases.append(current)

        elif current:
            classes = [c.lower() for c in a.get("class", [])]

            is_direct = (
                "DIRECT" in raw_text.upper()
                or "cyberloom" in href_lower
                or any("download" in c for c in classes)
            )

            if is_direct:
                if href.startswith("http") and not current["direct_link"]:
                    current["direct_link"] = href
            elif href.startswith("magnet:"):
                if not current["magnet"]:
                    current["magnet"] = href

    if not releases:
        return None

    title_tag = soup.find("h1") or soup.find("title")
    topic_title = (
        clean_release_title(title_tag.get_text()) if title_tag else releases[0]["title"]
    )

    logging.info(
        f"Parsed topic with {len(releases)} release(s) - "
        f"Poster: {'Yes' if poster_url else 'No'}"
    )

    return {
        "topic_url": topic_url,
        "title": topic_title,
        "poster_url": poster_url,
        "releases": releases,
    }


def crawl_tbl():
    topics = []
    crawl_ok = False
    topic_parse_failed = False
    scraper = create_scraper()

    try:
        discover_active_domain()

        logging.info("========================================")
        logging.info("Checking 1TamilMV...")
        logging.info(f"Active Base URL: {BASE_URL}")
        logging.info(f"Forum URL: {FORUM_URL}")

        try:
            response = scraper.get(FORUM_URL, timeout=20, headers={"Referer": BASE_URL})
            response.raise_for_status()
        except Exception as connection_error:
            logging.warning(
                f"Connection to {FORUM_URL} failed ({connection_error}). "
                "Attempting to rediscover active domain..."
            )
            discover_active_domain()
            response = scraper.get(FORUM_URL, timeout=20, headers={"Referer": BASE_URL})
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        topic_links = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href:
                continue
            if re.search(r"index\.php\?/forums/topic/", href, re.IGNORECASE) and not href.endswith("-0/"):
                topic_links.append(urljoin(BASE_URL, href))

        topic_links = list(dict.fromkeys(topic_links))
        logging.info(f"Found {len(topic_links)} topic links.")

        for topic_url in topic_links[:MAX_TOPICS]:
            try:
                topic = parse_topic(scraper, topic_url)
                if topic:
                    topics.append(topic)
            except Exception as topic_error:
                topic_parse_failed = True
                logging.error(f"Failed to parse topic {topic_url}: {topic_error}")

        crawl_ok = not topic_parse_failed

        if topic_parse_failed:
            logging.warning(
                "One or more topics failed to parse; treating this crawl as incomplete."
            )

        logging.info(f"1TamilMV crawl completed. Topics with releases: {len(topics)}")
        logging.info("========================================")

    except Exception as error:
        logging.error(f"Failed to fetch 1TamilMV forum: {error}")

    return topics, crawl_ok


def _rel_links(rel):
    return [l for l in (rel.get("torrent_link"), rel.get("direct_link"), rel.get("magnet")) if l]


def _norm(url):
    """Path+query only, no domain. So a domain change doesn't look like a new link."""
    if not url:
        return url
    p = urlparse(url)
    return p.path + (f"?{p.query}" if p.query else "")


class MN_Bot(Client):
    MAX_MSG_LENGTH = 4000

    def __init__(self):
        super().__init__(
            "Rss-Bot",
            api_id=API.ID,
            api_hash=API.HASH,
            bot_token=BOT.TOKEN,
            plugins={"root": "plugins"},
            workers=8,
        )

        self.channel_id = CHANNEL.ID
        self.last_posted = set()
        self.seen_topics = set()
        self.thumbnail_path = None
        self._crawl_task = None

        # Persistent state (Mongo if MONGO_URI set, else SQLite)
        self.db = StateDB()
        self.last_posted, self.seen_topics = self.db.load()
        logging.info(
            f"Loaded state: {len(self.last_posted)} posted links, "
            f"{len(self.seen_topics)} seen topics"
        )

    # ---------- state ----------

    def _mark_posted(self, link):
        if not link:
            return
        key = _norm(link)
        self.last_posted.add(key)
        self.db.add_link(key)

    def _mark_topic_seen(self, topic_url):
        if not topic_url:
            return
        key = _norm(topic_url)
        self.seen_topics.add(key)
        self.db.add_topic(key)

    # ---------- sending ----------

    async def safe_send_message(self, chat_id, text, **kwargs):
        for i in range(0, len(text), self.MAX_MSG_LENGTH):
            await self.send_message(chat_id, text[i:i + self.MAX_MSG_LENGTH], **kwargs)
            await asyncio.sleep(1)

    async def send_summary_post(self, topic_data):
        """Sends movie poster and direct links summary."""
        image_bytes = None

        try:
            releases = topic_data.get("releases", [])
            if not releases:
                return False

            blocks = []
            for rel in releases:
                title = escape((rel.get("title") or "").strip())
                direct_link = escape((rel.get("direct_link") or "").strip(), quote=True)

                if direct_link:
                    blocks.append(f"🎬 - {title}\n🔗 Direct Link: {direct_link}")
                else:
                    blocks.append(f"🎬 - {title}")

            if not blocks:
                return False

            # Telegram photo caption limit
            caption_chunks = []
            current_chunk = []
            current_len = 0

            for block in blocks:
                block_len = len(block)
                needed = block_len if not current_chunk else block_len + 2

                if current_chunk and current_len + needed > 950:
                    caption_chunks.append("\n\n".join(current_chunk))
                    current_chunk = [block]
                    current_len = block_len
                else:
                    current_chunk.append(block)
                    current_len += needed

            if current_chunk:
                caption_chunks.append("\n\n".join(current_chunk))

            first_caption = caption_chunks[0]
            remaining_chunks = caption_chunks[1:]

            poster_url = topic_data.get("poster_url")

            if poster_url:
                logging.info(f"Downloading poster from: {poster_url}")
                content = await asyncio.to_thread(
                    download_image, poster_url, topic_data.get("topic_url")
                )
                if content:
                    image_bytes = io.BytesIO(content)
                    image_bytes.name = "poster.jpg"

            max_retries = 3
            sent = False

            for attempt in range(max_retries):
                try:
                    if image_bytes:
                        logging.info("Sending summary post with movie poster...")
                        image_bytes.seek(0)
                        await self.send_photo(
                            self.channel_id,
                            photo=image_bytes,
                            caption=first_caption,
                            parse_mode=ParseMode.HTML,
                        )
                    elif self.thumbnail_path and os.path.exists(self.thumbnail_path):
                        logging.info("Sending summary post with default thumbnail...")
                        await self.send_photo(
                            self.channel_id,
                            photo=self.thumbnail_path,
                            caption=first_caption,
                            parse_mode=ParseMode.HTML,
                        )
                    else:
                        logging.info("Sending summary post as text message...")
                        await self.send_message(
                            self.channel_id,
                            first_caption,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=False,
                        )

                    sent = True
                    break

                except FloodWait as error:
                    logging.warning(
                        f"FloodWait in send_summary_post: waiting {error.value}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(error.value + 2)

                except Exception as error:
                    logging.error(f"Error in send_summary_post (attempt {attempt + 1}): {error}")
                    image_bytes = None  # photo failure -> fallback
                    await asyncio.sleep(2)

            if sent and remaining_chunks:
                for chunk in remaining_chunks:
                    await asyncio.sleep(1)
                    await self.safe_send_message(
                        self.channel_id,
                        chunk,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )

            return sent

        except Exception as error:
            logging.error(f"Failed in send_summary_post: {error}", exc_info=True)
            return False

        finally:
            if image_bytes:
                try:
                    image_bytes.close()
                except Exception:
                    pass

    async def send_torrent(self, file):
        file_bytes = None

        try:
            logging.info(f"Downloading torrent: {file['title']}")

            def _download():
                r = create_scraper().get(file["link"], timeout=30, headers={"Referer": BASE_URL})
                r.raise_for_status()
                return r.content

            content = await asyncio.to_thread(_download)
            file_bytes = io.BytesIO(content)

            clean_title = re.sub(r'[\\/:*?"<>|]', "_", file["title"]).strip()
            clean_title = re.sub(r"\s+", " ", clean_title).strip()

            safe_title = escape(clean_title)
            safe_size = escape(str(file.get("size", "Unknown")))

            filename = f"{clean_title.replace(' ', '_')}.torrent"
            file_bytes.name = filename

            caption = (
                f"🎬 <b>{safe_title}</b>\n\n"
                f"📦 <b>Size:</b> {safe_size}\n"
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
                        logging.info("Sending torrent with thumbnail...")
                        await self.send_document(
                            self.channel_id,
                            file_bytes,
                            file_name=filename,
                            thumb=thumb,
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                        )
                    else:
                        logging.warning("Thumbnail unavailable. Sending without thumbnail.")
                        await self.send_document(
                            self.channel_id,
                            file_bytes,
                            file_name=filename,
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                        )

                    logging.info(f"Successfully posted: {file['title']}")
                    return True

                except FloodWait as error:
                    logging.warning(
                        f"Hit FloodWait! Waiting {error.value}s before retry "
                        f"(attempt {attempt + 1}/{max_retries})..."
                    )
                    await asyncio.sleep(error.value + 2)
                    file_bytes.seek(0)

                except Exception as doc_error:
                    logging.error(f"Failed to send document to Telegram: {doc_error}")
                    return False

            return False

        except Exception as error:
            logging.error(f"Error processing/downloading TBL file {file['link']}: {error}")
            return False

        finally:
            if file_bytes:
                try:
                    file_bytes.close()
                except Exception:
                    pass

    # ---------- main loop ----------

    async def auto_post_torrents(self):
        logging.info("Automatic 1TamilMV posting started.")

        # Only silently cache on the very first ever run.
        # If state exists, detect releases added while bot was offline.
        is_first_run = not self.last_posted and not self.seen_topics

        while True:
            backlog = False

            try:
                topics, crawl_ok = await asyncio.to_thread(crawl_tbl)

                if not crawl_ok:
                    logging.warning(
                        "Crawl was incomplete or failed. Skipping state updates "
                        "and retrying next interval."
                    )

                elif not topics:
                    logging.warning(
                        "No topics returned from 1TamilMV. Will retry on next check interval."
                    )

                else:
                    topics.reverse()  # older unseen topics first

                    if is_first_run:
                        logging.info(
                            "First run detected. Caching current topics silently "
                            "to avoid spamming old posts."
                        )

                    posted_topics = 0

                    for topic_data in topics:
                        topic_url = topic_data["topic_url"]
                        releases = topic_data.get("releases", [])

                        new_releases = [
                            rel for rel in releases
                            if any(_norm(l) not in self.last_posted for l in _rel_links(rel))
                        ]

                        # First-ever run: silently cache
                        if is_first_run:
                            self._mark_topic_seen(topic_url)
                            for rel in releases:
                                for link in _rel_links(rel):
                                    self._mark_posted(link)
                            continue

                        # Already processed topic
                        if _norm(topic_url) in self.seen_topics and not new_releases:
                            continue

                        # Backlog cap (e.g. after long downtime). Skipped topics stay
                        # unmarked, so the next cycle picks them up (oldest first).
                        if posted_topics >= LIMITS.POST_LIMIT:
                            backlog = True
                            break

                        logging.info(f"Topic: {topic_data.get('title', 'Unknown')}")
                        logging.info(f"New releases to post: {len(new_releases)}")

                        already_seen = _norm(topic_url) in self.seen_topics
                        releases_to_send = new_releases if already_seen else releases

                        # 1. Send torrent documents
                        for rel in releases_to_send:
                            torrent_link = rel.get("torrent_link")

                            if torrent_link and _norm(torrent_link) not in self.last_posted:
                                file_info = {
                                    "title": rel["title"],
                                    "link": torrent_link,
                                    "size": rel.get("size", "Unknown"),
                                }

                                if await self.send_torrent(file_info):
                                    self._mark_posted(torrent_link)
                                    await asyncio.sleep(3)

                        # 2. Send poster+caption ONLY for releases that have a
                        # direct link. Torrent-only releases already got the
                        # file in step 1 — no extra poster post for them.
                        direct_releases = [r for r in releases_to_send if r.get("direct_link")]

                        topic_to_post = dict(topic_data)
                        topic_to_post["releases"] = direct_releases

                        summary_sent = True
                        if direct_releases:
                            summary_sent = await self.send_summary_post(topic_to_post)

                        if summary_sent:
                            for rel in releases_to_send:
                                if rel.get("direct_link"):
                                    self._mark_posted(rel["direct_link"])
                                if rel.get("magnet"):
                                    self._mark_posted(rel["magnet"])

                            self._mark_topic_seen(topic_url)
                            posted_topics += 1
                            await asyncio.sleep(2)

                    if is_first_run:
                        logging.info(
                            "Initial cache complete. The bot will now only "
                            "post newly added torrents."
                        )
                        is_first_run = False

            except asyncio.CancelledError:
                raise

            except Exception as error:
                logging.error(f"Error in auto_post_torrents: {error}", exc_info=True)

            if backlog:
                logging.info(
                    f"Backlog remains. Next cycle in {LIMITS.CATCHUP_INTERVAL}s."
                )
                await asyncio.sleep(LIMITS.CATCHUP_INTERVAL)
            else:
                logging.info("Tasks completed. Sleeping while waiting for new torrents...")
                await asyncio.sleep(CHECK_INTERVAL)

    async def _supervisor_loop(self):
        while True:
            try:
                await self.auto_post_torrents()

            except asyncio.CancelledError:
                logging.info("Auto-post supervisor cancelled.")
                break

            except Exception as error:
                logging.error(
                    f"Critical error in auto_post_torrents loop: {error}", exc_info=True
                )
                logging.info("Supervisor restarting auto_post_torrents in 30 seconds...")
                await asyncio.sleep(30)

    # ---------- lifecycle ----------

    async def start(self):
        await super().start()

        self.thumbnail_path = await asyncio.to_thread(sync_thumbnail, self.db)

        me = await self.get_me()
        BOT.USERNAME = f"@{me.username}" if me.username else me.first_name

        try:
            await self.send_message(
                OWNER.ID,
                text=(
                    f"{me.first_name} ✅ BOT STARTED\n\n"
                    f"📡 Source: 1TamilMV\n"
                    f"🔗 Forum: {FORUM_URL}\n"
                    f"⏱ Check: Every {CHECK_INTERVAL // 60} minutes\n"
                    f"🖼 Thumbnail: {'Enabled' if self.thumbnail_path else 'Disabled'}"
                ),
            )
        except Exception as error:
            logging.error(f"Could not notify owner: {error}")

        logging.info("RSS-Bot started successfully.")

        self._crawl_task = asyncio.create_task(self._supervisor_loop())

    async def stop(self, *args):
        logging.info("Stopping Rss-Bot...")

        if self._crawl_task and not self._crawl_task.done():
            self._crawl_task.cancel()
            try:
                await self._crawl_task
            except asyncio.CancelledError:
                pass

        await super().stop()
        logging.info("RSS-Bot stopped.")


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    MN_Bot().run()
