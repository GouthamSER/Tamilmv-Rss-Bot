import asyncio
import gc
import io
import json
import logging
import os
import re
import tempfile
import threading
import time
from collections import OrderedDict
from html import escape
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask

try:
    import lxml  # noqa: F401
    HTML_PARSER = "lxml"
except ImportError:
    HTML_PARSER = "html.parser"

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

from pyrogram import Client
from pyrogram import utils as pyroutils
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait

from config import API, BOT, CHANNEL, NETWORK, OWNER, WEB

# Support large 64-bit Telegram channel and chat IDs
pyroutils.MIN_CHAT_ID = -99999999999999
pyroutils.MIN_CHANNEL_ID = -100999999999999

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("TamilmvBot")
logging.getLogger("pyrogram").setLevel(logging.ERROR)

app = Flask(__name__)


@app.route("/")
def home():
    return "Tamilmv RSS Bot is running!"


@app.route("/health")
def health():
    return {"status": "ok", "service": "Tamilmv-Rss-Bot"}, 200


def run_flask():
    try:
        app.run(host="0.0.0.0", port=WEB.PORT, threaded=True)
    except Exception as e:
        logger.error(f"Flask server error: {e}")


GATEWAY_DOMAINS = [
    "https://www.1tamilmv.rocks",
    "https://1tamilmv.rocks",
    "https://www.1tamilmv.lease",
    "https://1tamilmv.lease",
    "https://www.1tamilmv.yt",
    "https://1tamilmv.yt",
    "https://www.1tamilmv.fi",
    "https://1tamilmv.fi",
]

BASE_URL = NETWORK.BASE_URL.rstrip("/") if NETWORK.BASE_URL else "https://www.1tamilmv.rocks"
FORUM_URL = f"{BASE_URL}/index.php?/forums/topic/"
MAX_TOPICS = 13
CHECK_INTERVAL = 600

# Memory guards
MAX_IMAGE_BYTES = 8 * 1024 * 1024      # poster cap
MAX_TORRENT_BYTES = 10 * 1024 * 1024   # .torrent cap
MAX_STATE_SIZE = 10000                 # remembered links / topics
DOMAIN_TTL = 3600                      # re-discover domain at most once per hour

# Persistent state file: use workspace directory by default so data survives container/OS reboots
DEFAULT_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rss_bot_state.json")
STATE_PATH = os.environ.get("STATE_PATH", DEFAULT_STATE_FILE)

THUMB_URL = "https://i.ibb.co/DPrwsGsC/IMG-20260919-174828-023.jpg"
THUMB_PATH = os.path.join(tempfile.gettempdir(), "tbl_thumb.jpg")

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_DOMAIN_CHECKED_AT = 0.0
_tls = threading.local()


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
            s.headers.update(DEFAULT_HEADERS)
            if NETWORK.PROXY:
                s.proxies = {
                    "http": NETWORK.PROXY,
                    "https": NETWORK.PROXY
                }
            return s
        except Exception as e:
            logger.warning(f"Cloudscraper initialization failed, falling back to requests: {e}")

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if NETWORK.PROXY:
        session.proxies = {
            "http": NETWORK.PROXY,
            "https": NETWORK.PROXY
        }
    return session


def get_scraper():
    """One reusable scraper per thread. Creating a new cloudscraper per call
    leaked sessions/sockets and was the main RAM growth."""
    s = getattr(_tls, "scraper", None)
    if s is None:
        s = create_scraper()
        _tls.scraper = s
    return s


def fetch_bytes(url, referer=None, max_bytes=MAX_IMAGE_BYTES, timeout=25):
    """Download with a hard size cap, streamed, so a huge file never fills RAM."""
    scraper = get_scraper()
    headers = {"Referer": referer} if referer else {}
    resp = scraper.get(url, timeout=timeout, headers=headers, stream=True)
    try:
        resp.raise_for_status()
        clen = resp.headers.get("Content-Length", "")
        if clen.isdigit() and int(clen) > max_bytes:
            raise ValueError(f"File too large ({clen} bytes)")
        buf = bytearray()
        for chunk in resp.iter_content(65536):
            if not chunk:
                continue
            buf.extend(chunk)
            if len(buf) > max_bytes:
                raise ValueError(f"File exceeded {max_bytes} bytes")
        if not buf:
            raise ValueError("Empty response")
        return bytes(buf)
    finally:
        resp.close()


def _set_active_domain(base):
    global BASE_URL, FORUM_URL, _DOMAIN_CHECKED_AT
    BASE_URL = base.rstrip("/")
    FORUM_URL = f"{BASE_URL}/index.php?/forums/topic/"
    _DOMAIN_CHECKED_AT = time.time()
    return BASE_URL


def _invalidate_domain_cache():
    global _DOMAIN_CHECKED_AT
    _DOMAIN_CHECKED_AT = 0.0


def discover_active_domain():
    """
    Checks gateway domains and follows redirects or reads
    the official announcement banner to discover the current active domain.
    Result is cached for DOMAIN_TTL seconds.
    """
    if NETWORK.BASE_URL:
        return _set_active_domain(NETWORK.BASE_URL)

    if _DOMAIN_CHECKED_AT and (time.time() - _DOMAIN_CHECKED_AT) < DOMAIN_TTL:
        return BASE_URL

    scraper = get_scraper()

    # 1. Test redirect gateways
    for gateway in ["https://www.1tamilmv.rocks", "https://www.1tamilmv.lease", "https://www.1tamilmv.fi"]:
        try:
            r = scraper.get(gateway, timeout=8, allow_redirects=False)
            if r.status_code in (301, 302, 307, 308) and r.headers.get("Location"):
                target = r.headers["Location"]
                parsed = urlparse(target)
                final_domain = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
                if "tamilmv" in final_domain.lower():
                    logger.info(f"Gateway {gateway} redirected to active domain: {final_domain}")
                    return _set_active_domain(final_domain)
        except Exception as e:
            logger.debug(f"Gateway check failed for {gateway}: {e}")

    # 2. Check known domains and official banner
    for dom in GATEWAY_DOMAINS:
        try:
            r = scraper.get(dom, timeout=10, allow_redirects=True)
            if r.status_code == 200:
                banner_match = re.search(
                    r"official\s+website.*?((?:WWW\.)?1TAMILMV\.[A-Z0-9.-]+)",
                    r.text,
                    re.IGNORECASE | re.DOTALL
                )
                if banner_match:
                    domain_name = banner_match.group(1).lower().strip()
                    if not domain_name.startswith("http"):
                        official = f"https://{domain_name}"
                    else:
                        official = domain_name
                    logger.info(f"Official domain discovered from site banner: {official}")
                    return _set_active_domain(official)

                parsed = urlparse(r.url)
                return _set_active_domain(f"{parsed.scheme}://{parsed.netloc}")
        except Exception as e:
            logger.debug(f"Known domain check failed for {dom}: {e}")

    return BASE_URL


def download_thumbnail():
    try:
        if os.path.exists(THUMB_PATH) and os.path.getsize(THUMB_PATH) > 0:
            logger.info(f"Thumbnail already exists: {THUMB_PATH}")
            return THUMB_PATH

        logger.info("Downloading Telegram thumbnail...")
        data = fetch_bytes(THUMB_URL, max_bytes=MAX_IMAGE_BYTES, timeout=20)

        with open(THUMB_PATH, "wb") as file:
            file.write(data)

        if not os.path.exists(THUMB_PATH) or os.path.getsize(THUMB_PATH) == 0:
            logger.error("Thumbnail file is empty.")
            return None

        logger.info(f"Thumbnail downloaded successfully: {THUMB_PATH}")
        return THUMB_PATH
    except Exception as e:
        logger.error(f"Failed to download thumbnail: {e}")
        return None


def download_image(url, referer=None):
    if not url or not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    try:
        return fetch_bytes(url, referer=referer, max_bytes=MAX_IMAGE_BYTES, timeout=25)
    except Exception as e:
        logger.warning(f"Failed to download image from {url}: {e}")
    return None


def extract_size(text):
    if not text:
        return "Unknown"
    match = re.search(
        r"(\d+(?:\.\d+)?\s*(?:GB|MB|KB))",
        text,
        re.IGNORECASE
    )
    return match.group(1).upper() if match else "Unknown"


def clean_release_title(raw_title):
    if not raw_title:
        return "1TamilMV Release"
    title = raw_title.replace("\xa0", " ").strip()
    # Strip site prefixes (e.g. www.1TamilMV.lease - , 1TamilMV.lease - , [1TamilMV] - )
    title = re.sub(
        r"^\[?(?:https?://)?(?:www\.)?1tamilmv\.[a-z0-9.-]+\]?\s*[-–—:]\s*",
        "",
        title,
        flags=re.IGNORECASE
    ).strip()
    title = re.sub(r"^www\.\S+\s*[-–—:]\s*", "", title, flags=re.IGNORECASE).strip()
    # Strip site suffixes
    title = re.sub(r"\s*[-–—:]\s*1TamilMV.*$", "", title, flags=re.IGNORECASE).strip()
    # Strip file extensions
    title = re.sub(r"\.(?:torrent|mkv|mp4|avi)$", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"\s+", " ", title).strip()
    return title or "1TamilMV Release"


def _extract_topic_id(url: str) -> str:
    """Extract numeric topic ID from topic URL (e.g. /topic/199974-...)"""
    m = re.search(r"/topic/(\d+)", url)
    return m.group(1) if m else ""


def _extract_attach_id(url: str) -> str:
    """Extract attachment ID from download URL (e.g. attachment.php?id=159140)"""
    m = re.search(r"attachment\.php\?id=(\d+)", url)
    return m.group(1) if m else ""


def _extract_btih(magnet: str) -> str:
    """Extract BitTorrent Info Hash from magnet link"""
    m = re.search(r"xt=urn:btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})", magnet)
    return m.group(1).lower() if m else ""


class BoundedSet:
    """Insertion-ordered set capped at maxlen. Oldest entries drop first
    (plain set + slice dropped random entries)."""

    def __init__(self, items=(), maxlen=MAX_STATE_SIZE):
        self.maxlen = maxlen
        self._d = OrderedDict()
        for item in items:
            self._d[item] = None
        self._trim()

    def _trim(self):
        while len(self._d) > self.maxlen:
            self._d.popitem(last=False)

    def add(self, item):
        self._d.pop(item, None)
        self._d[item] = None
        self._trim()

    def __contains__(self, item):
        return item in self._d

    def __len__(self):
        return len(self._d)

    def __iter__(self):
        return iter(self._d)


def crawl_tbl():
    topics = []
    scraper = get_scraper()

    try:
        discover_active_domain()

        logger.info("========================================")
        logger.info("Checking 1TamilMV...")
        logger.info(f"Active Base URL: {BASE_URL}")
        logger.info(f"Forum URL: {FORUM_URL}")

        # Fetch forum listing (with fallback to BASE_URL)
        response = None
        for endpoint in [FORUM_URL, f"{BASE_URL}/", f"{BASE_URL}/index.php?/forums/"]:
            try:
                r = scraper.get(endpoint, timeout=20, headers={"Referer": BASE_URL})
                if r.status_code == 200 and len(r.text) > 1000:
                    response = r
                    break
            except Exception as conn_err:
                logger.debug(f"Fetching {endpoint} failed: {conn_err}")

        if not response:
            logger.warning("Could not reach 1TamilMV forum listing from any known endpoint.")
            _invalidate_domain_cache()  # domain may have changed; re-discover next round
            return topics

        soup = BeautifulSoup(response.text, HTML_PARSER)
        topic_links = []

        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href:
                continue

            clean_href = href.split("?")[0].split("#")[0]
            # Match standard topic links and skip pinned announcements (-0/)
            if re.search(r"index\.php\?/forums/topic/\d+-[^/]+/?$", clean_href, re.IGNORECASE):
                if not re.search(r"topic/\d+-0/?$", clean_href):
                    full_url = urljoin(BASE_URL, clean_href)
                    topic_links.append(full_url)
            elif re.search(r"index\.php\?/forums/topic/", href, re.IGNORECASE) and not href.endswith("-0/"):
                full_url = urljoin(BASE_URL, clean_href)
                topic_links.append(full_url)

        # Free listing page before fetching topics
        soup.decompose()
        del soup, response

        topic_links = list(dict.fromkeys(topic_links))
        logger.info(f"Found {len(topic_links)} unique topic links.")

        for topic_url in topic_links[:MAX_TOPICS]:
            post_soup = None
            try:
                logger.info(f"Checking topic: {topic_url}")
                topic_response = scraper.get(
                    topic_url,
                    timeout=20,
                    headers={"Referer": FORUM_URL}
                )
                topic_response.raise_for_status()

                post_soup = BeautifulSoup(topic_response.text, HTML_PARSER)
                del topic_response

                post = (
                    post_soup.find("div", attrs={"data-role": "commentContent"})
                    or post_soup.find("div", class_="cPost_contentWrap")
                )

                if not post:
                    continue

                # Extract Poster Image URL
                poster_url = None
                for img in post.find_all("img"):
                    src = (
                        img.get("src")
                        or img.get("data-src")
                        or img.get("data-lazy-src")
                        or img.get("data-original")
                    )
                    if not src:
                        continue
                    src_lower = src.lower()
                    if any(bad in src_lower for bad in [
                        "smilies", "border", "utorrent", "torrborder",
                        "default_large", "theme", "icon", "blank.gif", ".svg", "reaction"
                    ]):
                        continue
                    poster_url = urljoin(topic_url, src)
                    break

                page_title_tag = post_soup.find("h1") or post_soup.find("title")
                raw_page_title = str(page_title_tag.get_text()) if page_title_tag else ""

                releases = []
                current_rel = None

                for a in post.find_all("a"):
                    href = str(a.get("href", "")).strip()
                    data_fileext = a.get("data-fileext")
                    raw_text = str(a.get_text(" ", strip=True))

                    is_torrent = (
                        data_fileext == "torrent"
                        or ("attachment.php" in href and "key=" in href)
                        or (href.endswith(".torrent"))
                    )

                    if is_torrent:
                        candidate_title = raw_text or str(a.get("title", "")) or raw_page_title
                        clean_title = clean_release_title(candidate_title)
                        size = extract_size(raw_text or candidate_title)
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
                        href_lower = href.lower()
                        classes = [str(c).lower() for c in (a.get("class") or [])]
                        is_direct_candidate = (
                            "DIRECT" in raw_text.upper()
                            or "cyberloom" in href_lower
                            or any("download" in c for c in classes)
                        )
                        if is_direct_candidate:
                            if href.startswith("http") and not current_rel["direct_link"]:
                                current_rel["direct_link"] = href
                        elif href.startswith("magnet:") and not current_rel["magnet"]:
                            current_rel["magnet"] = href

                if releases:
                    topic_title = (
                        clean_release_title(raw_page_title)
                        if raw_page_title else releases[0]["title"]
                    )

                    topics.append({
                        "topic_url": topic_url,
                        "title": topic_title,
                        "poster_url": poster_url,
                        "releases": releases,
                    })

                    logger.info(
                        f"Parsed topic with {len(releases)} release(s) - Poster: {'Yes' if poster_url else 'No'}"
                    )

            except Exception as topic_error:
                logger.error(f"Failed to parse topic {topic_url}: {topic_error}")
            finally:
                # Always free the parsed DOM of this topic
                if post_soup is not None:
                    try:
                        post_soup.decompose()
                    except Exception:
                        pass
                    post_soup = None

        logger.info(f"1TamilMV crawl completed. Topics with releases: {len(topics)}")
        logger.info("========================================")

    except Exception as error:
        logger.error(f"Failed to fetch 1TamilMV forum: {error}")

    return topics


class MN_Bot(Client):
    MAX_MSG_LENGTH = 3800

    def __init__(self):
        super().__init__(
            "Rss-Bot",
            api_id=API.ID,
            api_hash=API.HASH,
            bot_token=BOT.TOKEN,
            plugins={"root": "plugins"},
            workers=2
        )

        self.channel_id = CHANNEL.ID
        self.last_posted = BoundedSet()
        self.seen_topics = BoundedSet()
        self.thumbnail_path = None
        self._crawl_task = None
        self._state_lock = threading.Lock()
        self.is_first_run = False
        self._load_state()

    def _load_state(self):
        """Load posted-link/topic state from disk so restarts do not lose history."""
        self.last_posted = BoundedSet()
        self.seen_topics = BoundedSet()

        load_path = STATE_PATH
        legacy_temp = os.path.join(tempfile.gettempdir(), "rss_bot_state.json")
        if not os.path.exists(load_path) and os.path.exists(legacy_temp):
            load_path = legacy_temp

        try:
            if not os.path.exists(load_path):
                return

            with open(load_path, "r", encoding="utf-8") as file:
                state = json.load(file)

            self.last_posted = BoundedSet(state.get("last_posted", []))
            self.seen_topics = BoundedSet(state.get("seen_topics", []))

            logger.info(
                f"Loaded state: {len(self.last_posted)} posted links, "
                f"{len(self.seen_topics)} seen topics from {load_path}"
            )
        except Exception as e:
            logger.warning(f"Could not load persistent state: {e}")

    def _save_state(self):
        """Persist posted-link/topic state atomically (oldest entries already trimmed)."""
        try:
            state = {
                "last_posted": list(self.last_posted),
                "seen_topics": list(self.seen_topics),
            }

            temp_path = f"{STATE_PATH}.tmp"
            with self._state_lock:
                with open(temp_path, "w", encoding="utf-8") as file:
                    json.dump(state, file, ensure_ascii=False)
                os.replace(temp_path, STATE_PATH)
        except Exception as e:
            logger.warning(f"Could not save persistent state: {e}")

    def _is_topic_seen(self, topic_url: str) -> bool:
        """Check if topic was seen by URL or by stable numeric topic ID."""
        if topic_url in self.seen_topics:
            return True
        t_id = _extract_topic_id(topic_url)
        return bool(t_id and f"topic:{t_id}" in self.seen_topics)

    def _mark_topic_seen(self, topic_url: str):
        """Record topic URL and normalized numeric topic ID."""
        self.seen_topics.add(topic_url)
        t_id = _extract_topic_id(topic_url)
        if t_id:
            self.seen_topics.add(f"topic:{t_id}")

    def _is_link_posted(self, link: str) -> bool:
        """Check if link was already posted by URL, attachment ID, or magnet hash."""
        if not link:
            return True
        if link in self.last_posted:
            return True
        a_id = _extract_attach_id(link)
        if a_id and f"attach:{a_id}" in self.last_posted:
            return True
        if link.startswith("magnet:"):
            btih = _extract_btih(link)
            if btih and f"btih:{btih}" in self.last_posted:
                return True
        return False

    def _mark_link_posted(self, link: str):
        """Record link by URL, attachment ID, and magnet hash."""
        if not link:
            return
        self.last_posted.add(link)
        a_id = _extract_attach_id(link)
        if a_id:
            self.last_posted.add(f"attach:{a_id}")
        if link.startswith("magnet:"):
            btih = _extract_btih(link)
            if btih:
                self.last_posted.add(f"btih:{btih}")

    async def safe_send_message(self, chat_id, text, **kwargs):
        for i in range(0, len(text), self.MAX_MSG_LENGTH):
            chunk = text[i:i + self.MAX_MSG_LENGTH]
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    await self.send_message(chat_id, chunk, **kwargs)
                    break
                except FloodWait as e:
                    logger.warning(f"FloodWait in safe_send_message: waiting {e.value}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(e.value + 1)
                except Exception as e:
                    logger.error(f"Error in safe_send_message: {e}")
                    break
            await asyncio.sleep(1)

    async def send_summary_post(self, topic_data):
        """
        Sends movie poster and direct links summary post formatted as:
        🎬 - {Release Title}
        🔗 Direct Link: {Direct Link}
        """
        image_bytes = None
        try:
            releases = topic_data.get("releases", [])
            if not releases:
                return False

            blocks = []
            for rel in releases:
                # Cap RAW title first, escape after -> never cut inside an HTML entity
                title = (rel.get("title") or "").strip()[:200]
                direct_link = (rel.get("direct_link") or "").strip()
                safe_title = escape(title)
                safe_direct_link = escape(direct_link)

                if direct_link:
                    block = (
                        f"🎬 - {safe_title}\n"
                        f"🔗 Direct Link: {safe_direct_link}"
                    )
                    if len(block) > 950:
                        block = f"🎬 - {safe_title}"
                else:
                    block = f"🎬 - {safe_title}"
                blocks.append(block)

            if not blocks:
                return False

            # Telegram photo caption limit is 1024 characters.
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
            if poster_url:
                logger.info(f"Downloading poster from: {poster_url}")
                image_content = await asyncio.to_thread(
                    download_image,
                    poster_url,
                    topic_data.get("topic_url")
                )
                if image_content:
                    image_bytes = io.BytesIO(image_content)
                    image_bytes.name = "poster.jpg"
                    del image_content

            max_retries = 3
            sent_successfully = False

            for attempt in range(max_retries):
                try:
                    if image_bytes:
                        logger.info("Sending summary post with movie poster...")
                        image_bytes.seek(0)
                        await self.send_photo(
                            self.channel_id,
                            photo=image_bytes,
                            caption=first_caption,
                            parse_mode=ParseMode.HTML
                        )
                    elif self.thumbnail_path and os.path.exists(self.thumbnail_path):
                        logger.info("Sending summary post with default thumbnail...")
                        await self.send_photo(
                            self.channel_id,
                            photo=self.thumbnail_path,
                            caption=first_caption,
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        logger.info("Sending summary post as text message...")
                        await self.send_message(
                            self.channel_id,
                            first_caption,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True
                        )

                    sent_successfully = True
                    break

                except FloodWait as e:
                    logger.warning(
                        f"FloodWait in send_summary_post: waiting {e.value}s (attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(e.value + 2)
                except Exception as e:
                    logger.error(f"Error in send_summary_post (attempt {attempt + 1}): {e}")
                    image_bytes = None
                    await asyncio.sleep(2)

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

        except Exception:
            logger.exception("Failed in send_summary_post")
            return False
        finally:
            if image_bytes:
                try:
                    image_bytes.close()
                except Exception as close_err:
                    logger.debug(f"Error closing image_bytes: {close_err}")

    async def send_torrent(self, file):
        file_bytes = None
        try:
            logger.info(f"Downloading torrent: {file['title']}")

            content = await asyncio.to_thread(
                fetch_bytes,
                file["link"],
                BASE_URL,
                MAX_TORRENT_BYTES,
                30
            )
            file_bytes = io.BytesIO(content)
            del content

            clean_title = re.sub(r'[\\/:*?"<>|]', "_", file["title"]).strip()
            clean_title = re.sub(r"\s+", " ", clean_title).strip()

            filename = f"{clean_title.replace(' ', '_')}.torrent"
            file_bytes.name = filename

            safe_title = escape(clean_title)
            safe_size = escape(str(file.get("size", "Unknown")))

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
                    file_bytes.seek(0)
                    if thumb:
                        logger.info("Sending torrent with thumbnail...")
                        await self.send_document(
                            self.channel_id,
                            file_bytes,
                            file_name=filename,
                            thumb=thumb,
                            caption=caption,
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        logger.warning("Sending torrent without thumbnail...")
                        await self.send_document(
                            self.channel_id,
                            file_bytes,
                            file_name=filename,
                            caption=caption,
                            parse_mode=ParseMode.HTML
                        )

                    logger.info(f"Successfully posted: {file['title']}")
                    return True

                except FloodWait as e:
                    logger.warning(
                        f"Hit FloodWait! Waiting {e.value}s before retry (attempt {attempt + 1}/{max_retries})..."
                    )
                    await asyncio.sleep(e.value + 2)
                except Exception as doc_err:
                    logger.error(
                        f"Failed to send document to Telegram (attempt {attempt + 1}/{max_retries}): {doc_err}"
                    )
                    thumb = None  # Fall back to sending without thumb
                    if attempt + 1 < max_retries:
                        await asyncio.sleep(2)
                    else:
                        return False

            return False

        except Exception as error:
            logger.error(
                f"Error processing/downloading TBL file {file['link']}: {error}"
            )
            return False
        finally:
            if file_bytes:
                try:
                    file_bytes.close()
                except Exception as close_err:
                    logger.debug(f"Error closing file_bytes: {close_err}")

    async def auto_post_torrents(self):
        logger.info("Automatic 1TamilMV posting started.")

        # Clean startup check: only suppress posting if bot has NEVER recorded any seen topics/posts
        if not self.seen_topics and not self.last_posted:
            self.is_first_run = True
            logger.info("First run on clean state detected. Existing topics will be cached without spamming the channel.")
        else:
            self.is_first_run = False
            logger.info(
                f"Resuming with {len(self.seen_topics)} seen topics and {len(self.last_posted)} cached links."
            )

        while True:
            try:
                topics = await asyncio.to_thread(crawl_tbl)

                if not topics:
                    logger.warning("No topics returned from 1TamilMV. Will retry on next check interval.")
                else:
                    topics.reverse()

                    for topic_data in topics:
                        topic_url = topic_data["topic_url"]
                        releases = topic_data.get("releases", [])

                        def _rel_links(rel):
                            return [
                                lnk for lnk in (
                                    rel.get("torrent_link"),
                                    rel.get("direct_link"),
                                    rel.get("magnet"),
                                )
                                if lnk
                            ]

                        # Check for new releases using cross-domain link checker
                        new_releases = [
                            rel
                            for rel in releases
                            if any(not self._is_link_posted(link) for link in _rel_links(rel))
                        ]

                        # If first run on clean state, cache everything silently
                        if self.is_first_run:
                            self._mark_topic_seen(topic_url)
                            for rel in releases:
                                for link in _rel_links(rel):
                                    self._mark_link_posted(link)
                            continue

                        # If topic already seen and no new releases, skip
                        if self._is_topic_seen(topic_url) and not new_releases:
                            continue

                        logger.info(f"Topic: {topic_data.get('title', 'Unknown')}")
                        logger.info(f"New releases to post: {len(new_releases)}")

                        releases_to_send = (
                            new_releases if self._is_topic_seen(topic_url) else releases
                        )

                        # 1. Send the individual .torrent file documents FIRST
                        for rel in releases_to_send:
                            torrent_link = rel.get("torrent_link")
                            if torrent_link and not self._is_link_posted(torrent_link):
                                file_info = {
                                    "title": rel["title"],
                                    "link": torrent_link,
                                    "size": rel.get("size", "Unknown")
                                }
                                success = await self.send_torrent(file_info)
                                if success:
                                    self._mark_link_posted(torrent_link)
                                    self._save_state()
                                    await asyncio.sleep(3)

                        # 2. Send Summary Post AFTER torrent files
                        topic_to_post = dict(topic_data)
                        if self._is_topic_seen(topic_url):
                            topic_to_post["releases"] = new_releases

                        summary_posted = await self.send_summary_post(topic_to_post)
                        if summary_posted:
                            for rel in releases_to_send:
                                direct_link = rel.get("direct_link")
                                magnet = rel.get("magnet")
                                if direct_link:
                                    self._mark_link_posted(direct_link)
                                if magnet:
                                    self._mark_link_posted(magnet)

                            self._save_state()
                            await asyncio.sleep(2)

                        self._mark_topic_seen(topic_url)
                        self._save_state()

                    if self.is_first_run:
                        self._save_state()
                        logger.info("Initial cache complete. The bot will now only post newly added torrents.")
                        self.is_first_run = False

                # Drop crawl results and return freed memory each cycle
                topics = None
                gc.collect()

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in auto_post_torrents")

            logger.info("Tasks completed. Sleeping while waiting for new torrents...")
            await asyncio.sleep(CHECK_INTERVAL)

    async def _supervisor_loop(self):
        while True:
            try:
                await self.auto_post_torrents()
            except asyncio.CancelledError:
                logger.info("Auto-post supervisor cancelled.")
                break
            except Exception:
                logger.exception("Critical error in auto_post_torrents loop")
                logger.info("Supervisor restarting auto_post_torrents in 30 seconds...")
                await asyncio.sleep(30)

    async def start(self):
        await super().start()

        self.thumbnail_path = await asyncio.to_thread(download_thumbnail)

        me = await self.get_me()
        BOT.USERNAME = f"@{me.username}" if me.username else me.first_name

        if OWNER.ID:
            try:
                await self.send_message(
                    OWNER.ID,
                    text=(
                        f"{me.first_name} ✅ BOT STARTED\n\n"
                        f"📡 Source: 1TamilMV\n"
                        f"🔗 Forum: {FORUM_URL}\n"
                        f"⏱ Check: Every {CHECK_INTERVAL // 60} minutes\n"
                        f"🖼 Thumbnail: "
                        f"{'Enabled' if self.thumbnail_path else 'Disabled'}"
                    )
                )
            except Exception as error:
                logger.error(f"Could not notify owner: {error}")

        logger.info("RSS-Bot started successfully.")

        self._crawl_task = asyncio.create_task(
            self._supervisor_loop()
        )

    async def stop(self, *args, **kwargs):
        logger.info("Stopping Rss-Bot...")

        if self._crawl_task and not self._crawl_task.done():
            self._crawl_task.cancel()
            try:
                await self._crawl_task
            except asyncio.CancelledError:
                pass

        await super().stop(*args, **kwargs)
        logger.info("RSS-Bot stopped.")


if __name__ == "__main__":
    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    MN_Bot().run()
