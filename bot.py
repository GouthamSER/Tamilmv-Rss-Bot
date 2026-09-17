import asyncio
import logging
import threading
import io

from flask import Flask
from bs4 import BeautifulSoup
import cloudscraper
import re

from pyrogram import Client, errors, utils as pyroutils
from config import BOT, API, OWNER, CHANNEL

# Ensure proper chat/channel ID handling
pyroutils.MIN_CHAT_ID = -999999999999
pyroutils.MIN_CHANNEL_ID = -10099999999999

# Logging configuration
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

# Flask health check
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

# Run Flask in a separate thread
def run_flask():
    app.run(host='0.0.0.0', port=8000)

# Utility to extract size from text
def extract_size(text):
    match = re.search(r"(\d+(?:\.\d+)?\s*(?:GB|MB|KB))", text, re.IGNORECASE)
    return match.group(1) if match else "Unknown"

# Crawl 1TamilBlasters for torrent files, returning topic URL + its files
def crawl_tbl():
    base_url = "https://www.1tamilmv.rocks"
    torrents = []
    scraper = cloudscraper.create_scraper()

    try:
        resp = scraper.get(base_url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        topic_links = [
            a["href"] for a in soup.find_all("a", href=re.compile(r'/forums/topic/'))
            if a.get("href")
        ]
        # dedupe and limit to first 15 topics
        for rel_url in list(dict.fromkeys(topic_links))[:15]:
            try:
                full_url = rel_url if rel_url.startswith("http") else base_url + rel_url
                dresp = scraper.get(full_url, timeout=10)
                dresp.raise_for_status()
                post_soup = BeautifulSoup(dresp.text, "html.parser")

                torrent_tags = post_soup.find_all("a", attrs={"data-fileext": "torrent"})
                file_links = []
                for tag in torrent_tags:
                    href = tag.get("href")
                    if not href:
                        continue
                    link = href.strip()
                    raw_text = tag.get_text(strip=True)
                    title = raw_text.replace("www.1TamilBlasters.red - ", "")\
                                    .rstrip(".torrent").strip()
                    size = extract_size(raw_text)

                    file_links.append({
                        "type": "torrent",
                        "title": title,
                        "link": link,
                        "size": size
                    })

                if file_links:
                    torrents.append({
                        "topic_url": full_url,
                        "title": file_links[0]["title"],
                        "size": file_links[0]["size"],
                        "links": file_links
                    })

            except Exception as post_err:
                logging.error(f"Failed to parse TBL topic {rel_url}: {post_err}")

    except Exception as e:
        logging.error(f"Failed to fetch TBL homepage: {e}")

    return torrents

class MN_Bot(Client):
    MAX_MSG_LENGTH = 4000

    def __init__(self):
        super().__init__(
            "MN-Bot",
            api_id=API.ID,
            api_hash=API.HASH,
            bot_token=BOT.TOKEN,
            plugins=dict(root="plugins"),
            workers=8
        )
        self.channel_id = CHANNEL.ID
        self.last_posted = set()   # tracks individual file links
        self.seen_topics = set()   # tracks which topic URLs have been processed

    async def safe_send_message(self, chat_id, text, **kwargs):
        # split overly-long messages
        for chunk in (text[i:i+self.MAX_MSG_LENGTH] for i in range(0, len(text), self.MAX_MSG_LENGTH)):
            await self.send_message(chat_id, chunk, **kwargs)
            await asyncio.sleep(1)

    async def auto_post_torrents(self):
        while True:
            try:
                torrents = crawl_tbl()
                for t in torrents:
                    topic = t["topic_url"]
                    # find brand‑new files in this topic
                    new_files = [f for f in t["links"] if f["link"] not in self.last_posted]
                    # if we've seen this topic and there are no new files, skip
                    if topic in self.seen_topics and not new_files:
                        continue

                    # send each new file
                    for file in new_files:
                        try:
                            scraper = cloudscraper.create_scraper()
                            resp = scraper.get(file["link"], timeout=10)
                            resp.raise_for_status()
                            file_bytes = io.BytesIO(resp.content)
                            thumbnail ="https://ibb.co/Xr74g2gB"
                            filename = file["title"].replace(" ", "_") + ".torrent"
                            caption = (
                                f"{file['title']}\n"
                                f"📦 {file['size']}\n"
                                "#tbl torrent file"
                            )
                            await self.send_document(
                                self.channel_id,
                                file_bytes,
                                file_name=filename,
                                thumb=thumbnail,
                                caption=caption
                            )
                            self.last_posted.add(file["link"])
                            logging.info(f"Posted TBL: {file['title']}")
                            await asyncio.sleep(3)
                        except Exception as e:
                            logging.error(f"Error sending TBL file {file['link']}: {e}")

                    # mark this topic as seen
                    self.seen_topics.add(topic)

            except Exception as e:
                logging.error(f"Error in auto_post_torrents: {e}")

            # wait 15 minutes before next check
            await asyncio.sleep(900)

    async def start(self):
        await super().start()
        me = await self.get_me()
        BOT.USERNAME = f"@{me.username}"
        await self.send_message(
            OWNER.ID,
            text=f"{me.first_name} ✅ BOT started with only TBL support (15‑min checks)"
        )
        logging.info("MN-Bot started with only TBL support")
        asyncio.create_task(self.auto_post_torrents())

    async def stop(self, *args):
        await super().stop()
        logging.info("MN-Bot stopped")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    MN_Bot().run()

