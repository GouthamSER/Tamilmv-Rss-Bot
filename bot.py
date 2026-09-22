import asyncio
import io
import json
import logging
import os
import re
import tempfile
import threading
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
from config import BOT, API, OWNER, CHANNEL, WEB, NETWORK

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
    "https://www.1tamilmv.lease",
]

BASE_URL = NETWORK.BASE_URL.rstrip("/") if NETWORK.BASE_URL else "https://www.1tamilmv.rocks"
FORUM_URL = f"{BASE_URL}/index.php?/forums/topic/"
MAX_TOPICS = 15
CHECK_INTERVAL = 480

THUMB_URL = "https://i.ibb.co/DPrwsGsC/IMG-20260919-174828-023.jpg"
THUMB_PATH = os.path.join(tempfile.gettempdir(), "tbl_thumb.jpg")

# Posted-state persisted to disk. Old code kept last_posted/seen_topics only in
# RAM, so every restart wiped them -> bot lost track of what it already sent.
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "posted_state.json")

def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
            return set(data.get("last_posted", [])), set(data.get("seen_topics", []))
    except Exception as e:
        logging.error(f"Failed to load posted state: {e}")
    return set(), set()

def save_state(last_posted, seen_topics):
    try:
        tmp_path = STATE_FILE + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump({
                "last_posted": list(last_posted),
                "seen_topics": list(seen_topics)
            }, f)
        os.replace(tmp_path, STATE_FILE)
    except Exception as e:
        logging.error(f"Failed to save posted state: {e}")

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def create_scraper():
    if HAS_CLOUDSCRAPER:
        try:
            s = cloudscraper.create_scraper(
                browser={
                    "browser": "chrome",
                    "platform": "windows",
                    "mobile": False
                }
            )
            if NETWORK.PROXY:
                s.proxies = {
                    "http": NETWORK.PROXY,
                    "https": NETWORK.PROXY
                }
            return s
        except Exception:
            pass

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if NETWORK.PROXY:
        session.proxies = {
            "http": NETWORK.PROXY,
            "https": NETWORK.PROXY
        }
    return session

def discover_active_domain():
    """
    Checks gateway domains (e.g. WWW.1TAMILMV.FI) and follows redirects or reads
    the official announcement banner to automatically discover the current active domain.
    """
    global BASE_URL, FORUM_URL

    if NETWORK.BASE_URL:
        BASE_URL = NETWORK.BASE_URL.rstrip("/")
        FORUM_URL = f"{BASE_URL}/index.php?/forums/topic/"
        return BASE_URL

    scraper = create_scraper()

    # 1. Test permanent redirect gateway (WWW.1TAMILMV.FI)
    for gateway in ["https://www.1tamilmv.fi", "https://1tamilmv.fi"]:
        try:
            r = scraper.get(gateway, timeout=8, allow_redirects=False)
            if r.status_code in (301, 302, 307, 308) and r.headers.get("Location"):
                target = r.headers["Location"]
                parsed = urlparse(target)
                final_domain = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
                if "tamilmv" in final_domain.lower():
                    logging.info(f"Gateway {gateway} redirected to active domain: {final_domain}")
                    BASE_URL = final_domain
                    FORUM_URL = f"{BASE_URL}/index.php?/forums/topic/"
                    return BASE_URL
        except Exception as e:
            logging.debug(f"Gateway check failed for {gateway}: {e}")

    # 2. Check current known domains and check official announcement banner
    for dom in GATEWAY_DOMAINS:
        try:
            r = scraper.get(dom, timeout=10, allow_redirects=True)
            if r.status_code == 200:
                banner_match = re.search(
                    r"official\s+website\s+(WWW\.[A-Z0-9.-]+)",
                    r.text,
                    re.IGNORECASE
                )
                if banner_match:
                    official = f"https://{banner_match.group(1).lower()}".rstrip("/")
                    logging.info(f"Official domain discovered from site banner: {official}")
                    BASE_URL = official
                    FORUM_URL = f"{BASE_URL}/index.php?/forums/topic/"
                    return BASE_URL

                parsed = urlparse(r.url)
                base = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
                BASE_URL = base
                FORUM_URL = f"{BASE_URL}/index.php?/forums/topic/"
                return BASE_URL
        except Exception as e:
            logging.debug(f"Known domain check failed for {dom}: {e}")

    return BASE_URL

def download_thumbnail():
    try:
        if os.path.exists(THUMB_PATH) and os.path.getsize(THUMB_PATH) > 0:
            logging.info(f"Thumbnail already exists: {THUMB_PATH}")
            return THUMB_PATH

        logging.info("Downloading Telegram thumbnail...")
        scraper = create_scraper()
        response = scraper.get(
            THUMB_URL,
            timeout=20,
            headers={"User-Agent": DEFAULT_HEADERS["User-Agent"]}
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

def download_image(url, referer=None):
    try:
        scraper = create_scraper()
        headers = dict(DEFAULT_HEADERS)
        if referer:
            headers["Referer"] = referer
        response = scraper.get(url, timeout=25, headers=headers)
        response.raise_for_status()
        if response.content and len(response.content) > 0:
            return response.content
    except Exception as e:
        logging.warning(f"Failed to download image from {url}: {e}")
    return None

def extract_size(text):
    match = re.search(
        r"(\d+(?:\.\d+)?\s*(?:GB|MB|KB))",
        text,
        re.IGNORECASE
    )
    return match.group(1) if match else "Unknown"

def clean_release_title(raw_title):
    title = raw_title.strip()
    title = re.sub(r"^www\.\S+\s*-\s*", "", title, flags=re.IGNORECASE).strip()
    if title.lower().endswith(".torrent"):
        title = title[:-8].strip()
    if title.lower().endswith(".mkv"):
        title = title[:-4].strip()
    title = re.sub(r"\s+", " ", title).strip()
    return title or "1TamilMV Release"

def crawl_tbl():
    topics = []
    scraper = create_scraper()

    try:
        # Automatically discover or verify active domain from gateway
        discover_active_domain()

        logging.info("========================================")
        logging.info("Checking 1TamilMV...")
        logging.info(f"Active Base URL: {BASE_URL}")
        logging.info(f"Forum URL: {FORUM_URL}")

        try:
            response = scraper.get(
                FORUM_URL,
                timeout=20,
                headers={"Referer": BASE_URL}
            )
            response.raise_for_status()
        except Exception as conn_err:
            logging.warning(f"Connection to {FORUM_URL} failed ({conn_err}). Attempting to rediscover active domain...")
            discover_active_domain()
            response = scraper.get(
                FORUM_URL,
                timeout=20,
                headers={"Referer": BASE_URL}
            )
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        topic_links = []

        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href:
                continue

            if re.search(r"index\.php\?/forums/topic/", href, re.IGNORECASE) and not href.endswith("-0/"):
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

                post = (
                    post_soup.find("div", attrs={"data-role": "commentContent"})
                    or post_soup.find("div", class_="cPost_contentWrap")
                )

                if not post:
                    continue

                # Extract Poster Image URL
                poster_url = None
                for img in post.find_all("img"):
                    src = img.get("src") or img.get("data-src")
                    if not src:
                        continue
                    src_lower = src.lower()
                    if any(bad in src_lower for bad in [
                        "smilies", "border", "utorrent", "torrborder",
                        "default_large", "theme", "icon", "blank.gif"
                    ]):
                        continue
                    poster_url = urljoin(topic_url, src)
                    break

                # Extract Releases with matching Direct Links & Magnets
                releases = []
                current_rel = None

                for a in post.find_all("a"):
                    href = a.get("href", "").strip()
                    data_fileext = a.get("data-fileext")
                    raw_text = a.get_text(" ", strip=True)

                    is_torrent = (
                        data_fileext == "torrent"
                        or ("attachment.php" in href and "key=" in href)
                        or (href.endswith(".torrent"))
                    )

                    if is_torrent:
                        clean_title = clean_release_title(raw_text)
                        size = extract_size(raw_text)
                        full_tor_url = urljoin(topic_url, href)

                        current_rel = {
                            "title": clean_title,
                            "torrent_link": full_tor_url,
                            "size": size,
                            "direct_link": None,
                            "magnet": None,
                        }
                        releases.append(current_rel)
                    elif current_rel:
                        if (
                            "DIRECT" in raw_text.upper()
                            or "cyberloom" in href
                            or "download-button" in a.get("class", [])
                        ):
                            if href.startswith("http") and not current_rel["direct_link"]:
                                current_rel["direct_link"] = href
                        elif href.startswith("magnet:"):
                            if not current_rel["magnet"]:
                                current_rel["magnet"] = href

                if releases:
                    # Determine topic display title from first release or page title
                    page_title_tag = post_soup.find("h1") or post_soup.find("title")
                    topic_title = (
                        clean_release_title(page_title_tag.get_text())
                        if page_title_tag else releases[0]["title"]
                    )

                    topics.append({
                        "topic_url": topic_url,
                        "title": topic_title,
                        "poster_url": poster_url,
                        "releases": releases,
                    })

                    logging.info(
                        f"Parsed topic with {len(releases)} release(s) - Poster: {'Yes' if poster_url else 'No'}"
                    )

            except Exception as topic_error:
                logging.error(
                    f"Failed to parse topic {topic_url}: {topic_error}"
                )

        logging.info(
            f"1TamilMV crawl completed. Topics with releases: {len(topics)}"
        )
        logging.info("========================================")

    except Exception as error:
        logging.error(
            f"Failed to fetch 1TamilMV forum: {error}"
        )

    return topics

class MN_Bot(Client):
    MAX_MSG_LENGTH = 4000

    def __init__(self):
        super().__init__(
            "Rss-Bot",
            api_id=API.ID,
            api_hash=API.HASH,
            bot_token=BOT.TOKEN,
            plugins={"root": "plugins"},
            workers=8
        )

        self.channel_id = CHANNEL.ID
        # Real first run = no state file on disk yet. A restart with a state
        # file already there must NOT be treated as first run again.
        self._state_existed = os.path.exists(STATE_FILE)
        self.last_posted, self.seen_topics = load_state()
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

    async def send_summary_post(self, topic_data):
        """
        Sends movie poster and direct links summary post formatted as:
        🎬 - {Release Title}
        🔗 Direct Link: {Direct Link}
        """
        try:
            releases = topic_data.get("releases", [])
            if not releases:
                return False

            blocks = []
            for rel in releases:
                title = (rel.get("title") or "").strip()
                direct_link = (rel.get("direct_link") or "").strip()
                if direct_link:
                    blocks.append(f"🎬 - {title}\n🔗 Direct Link: {direct_link}")
                else:
                    blocks.append(f"🎬 - {title}")

            if not blocks:
                return False

            # Telegram photo caption limit is 1024 characters.
            # Group blocks into chunks to prevent MEDIA_CAPTION_TOO_LONG errors.
            caption_chunks = []
            current_chunk = []
            current_len = 0

            for block in blocks:
                block_len = len(block)
                needed = block_len if not current_chunk else (block_len + 2)
                if current_chunk and (current_len + needed > 950):
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

            # Attempt to download poster image
            poster_url = topic_data.get("poster_url")
            image_bytes = None
            if poster_url:
                logging.info(f"Downloading poster from: {poster_url}")
                image_content = await asyncio.to_thread(
                    download_image,
                    poster_url,
                    topic_data.get("topic_url")
                )
                if image_content:
                    image_bytes = io.BytesIO(image_content)
                    image_bytes.name = "poster.jpg"

            max_retries = 3
            sent_successfully = False

            for attempt in range(max_retries):
                try:
                    if image_bytes:
                        logging.info("Sending summary post with movie poster...")
                        image_bytes.seek(0)
                        await self.send_photo(
                            self.channel_id,
                            photo=image_bytes,
                            caption=first_caption,
                            parse_mode=ParseMode.HTML
                        )
                    elif self.thumbnail_path and os.path.exists(self.thumbnail_path):
                        logging.info("Sending summary post with default thumbnail...")
                        await self.send_photo(
                            self.channel_id,
                            photo=self.thumbnail_path,
                            caption=first_caption,
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        logging.info("Sending summary post as text message...")
                        await self.send_message(
                            self.channel_id,
                            first_caption,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=False
                        )

                    sent_successfully = True
                    break

                except FloodWait as e:
                    logging.warning(
                        f"FloodWait in send_summary_post: waiting {e.value}s (attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(e.value + 2)
                except Exception as e:
                    logging.error(f"Error in send_summary_post (attempt {attempt + 1}): {e}")
                    # If photo upload fails, fall back to text message on next attempt
                    image_bytes = None
                    await asyncio.sleep(2)

            # Send any subsequent chunks that could not fit into the photo caption
            if sent_successfully and remaining_chunks:
                for rem_chunk in remaining_chunks:
                    await asyncio.sleep(1)
                    await self.safe_send_message(
                        self.channel_id,
                        rem_chunk,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )

            return sent_successfully

        except Exception as err:
            logging.error(f"Failed in send_summary_post: {err}", exc_info=True)
            return False
        finally:
            if "image_bytes" in locals() and image_bytes:
                try:
                    image_bytes.close()
                except Exception:
                    pass

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

            # Clean title: strip illegal filename chars
            clean_title = re.sub(r'[\\/:*?"<>|]', "_", file["title"]).strip()
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
        finally:
            if "file_bytes" in locals() and file_bytes:
                try:
                    file_bytes.close()
                except Exception:
                    pass

    async def auto_post_torrents(self):
        logging.info("Automatic 1TamilMV posting started.")
        # Only silently cache on a genuine first-ever run (no state file).
        # After a restart with existing state, don't wipe/re-swallow it.
        is_first_run = not self._state_existed

        while True:
            try:
                # Run the blocking network crawler in a worker thread so the MTProto event loop never freezes
                topics = await asyncio.to_thread(crawl_tbl)

                if not topics:
                    logging.warning("No topics returned from 1TamilMV. Will retry on next check interval.")
                else:
                    # Reversing the list posts older unseen topics first
                    topics.reverse()

                    if is_first_run:
                        logging.info("First run detected. Caching current topics silently to avoid spamming old posts.")

                    for topic_data in topics:
                        topic_url = topic_data["topic_url"]
                        releases = topic_data.get("releases", [])

                        new_releases = [
                            rel
                            for rel in releases
                            if (rel.get("torrent_link") and rel["torrent_link"] not in self.last_posted)
                            or (rel.get("direct_link") and rel["direct_link"] not in self.last_posted)
                        ]

                        # Genuine first-ever run (no state file yet): cache everything silently
                        if is_first_run:
                            self.seen_topics.add(topic_url)
                            for rel in releases:
                                if rel.get("torrent_link"):
                                    self.last_posted.add(rel["torrent_link"])
                                if rel.get("direct_link"):
                                    self.last_posted.add(rel["direct_link"])
                            save_state(self.last_posted, self.seen_topics)
                            continue

                        # If topic already seen and no new releases, skip
                        if topic_url in self.seen_topics and not new_releases:
                            continue

                        logging.info(f"Topic: {topic_data.get('title', 'Unknown')}")
                        logging.info(f"New releases to post: {len(new_releases)}")

                        # 1. Send the .torrent file documents FIRST.
                        # If a release's torrent_link was already posted before
                        # (e.g. bot just restarted, or the site added the direct
                        # link a check-cycle later), do NOT resend the file —
                        # that was the "same torrent sent 2 times" bug. Only a
                        # release whose torrent itself was never sent gets sent.
                        releases_to_send = (
                            new_releases if topic_url in self.seen_topics else releases
                        )
                        newly_found_direct_links = []
                        for rel in releases_to_send:
                            torrent_link = rel.get("torrent_link")
                            direct_link = rel.get("direct_link")

                            if torrent_link and torrent_link in self.last_posted:
                                # Torrent already sent earlier. Direct link showed
                                # up later — no problem, just note it for the
                                # summary post below, don't resend the file.
                                if direct_link and direct_link not in self.last_posted:
                                    self.last_posted.add(direct_link)
                                    newly_found_direct_links.append(rel)
                                continue

                            if torrent_link:
                                file_info = {
                                    "title": rel["title"],
                                    "link": torrent_link,
                                    "size": rel.get("size", "Unknown")
                                }
                                success = await self.send_torrent(file_info)
                                if success:
                                    self.last_posted.add(torrent_link)
                                    if direct_link:
                                        self.last_posted.add(direct_link)
                                    save_state(self.last_posted, self.seen_topics)
                                    await asyncio.sleep(3)
                                # If it failed, don't mark it posted — next check
                                # (8 min later) will retry it, that's correct.
                            else:
                                if direct_link and direct_link not in self.last_posted:
                                    self.last_posted.add(direct_link)
                                    newly_found_direct_links.append(rel)

                        # 2. Send/refresh the Poster + Direct Links summary post,
                        # covering both brand-new releases and releases whose
                        # direct link only just became available.
                        summary_releases = new_releases if topic_url in self.seen_topics else releases
                        # dedupe, keep order
                        seen_ids = set(id(r) for r in summary_releases)
                        for r in newly_found_direct_links:
                            if id(r) not in seen_ids:
                                summary_releases.append(r)
                                seen_ids.add(id(r))

                        if summary_releases:
                            topic_to_post = dict(topic_data)
                            topic_to_post["releases"] = summary_releases
                            summary_posted = await self.send_summary_post(topic_to_post)
                            if summary_posted:
                                await asyncio.sleep(2)

                        self.seen_topics.add(topic_url)
                        save_state(self.last_posted, self.seen_topics)

                    if is_first_run:
                        logging.info("Initial cache complete. The bot will now only post newly added torrents.")
                        is_first_run = False
                        self._state_existed = True
                        save_state(self.last_posted, self.seen_topics)

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
            "RSS-Bot started successfully."
        )

        # Retain a strong task reference to prevent Python's garbage collector from destroying it mid-run
        self._crawl_task = asyncio.create_task(
            self._supervisor_loop()
        )

    async def stop(self, *args):
        logging.info(
            "Stopping Rss-Bot..."
        )

        if self._crawl_task and not self._crawl_task.done():
            self._crawl_task.cancel()
            try:
                await self._crawl_task
            except asyncio.CancelledError:
                pass

        await super().stop()

        logging.info(
            "RSS-Bot stopped."
        )

if __name__ == "__main__":
    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    MN_Bot().run()
