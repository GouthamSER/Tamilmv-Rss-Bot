"""
Persistent state for the bot (posted links + seen topics).

MONGO_URI set   -> saved in MongoDB (survives redeploys)
MONGO_URI empty -> bot still starts, nothing is saved, a log line says so
"""
import logging

from config import DATABASE


class StateDB:
    def __init__(self):
        self.links = None
        self.topics = None
        self.meta = None

        if not DATABASE.MONGO_URI:
            logging.warning("MONGO_URI not set. Bot starts, but state is NOT saved.")
            return

        try:
            from pymongo import MongoClient

            client = MongoClient(DATABASE.MONGO_URI, serverSelectionTimeoutMS=15000)
            client.admin.command("ping")
            db = client[DATABASE.DB_NAME]
            self.links = db["posted_links"]
            self.topics = db["seen_topics"]
            self.meta = db["meta"]
            logging.info("State DB: MongoDB connected.")
        except Exception as error:
            self.links = self.topics = self.meta = None
            logging.error(f"MongoDB connection failed: {error}. Bot starts, state is NOT saved.")

    @property
    def enabled(self):
        return self.links is not None

    def load(self):
        if not self.enabled:
            return set(), set()
        try:
            links = {d["_id"] for d in self.links.find({}, {"_id": 1})}
            topics = {d["_id"] for d in self.topics.find({}, {"_id": 1})}
            return links, topics
        except Exception as error:
            logging.error(f"DB load failed: {error}. State is NOT saved.")
            self.links = self.topics = self.meta = None
            return set(), set()

    def add_link(self, link):
        if not self.enabled:
            return
        try:
            self.links.update_one({"_id": link}, {"$setOnInsert": {"_id": link}}, upsert=True)
        except Exception as error:
            logging.error(f"DB add_link failed: {error}")

    def add_topic(self, url):
        if not self.enabled:
            return
        try:
            self.topics.update_one({"_id": url}, {"$setOnInsert": {"_id": url}}, upsert=True)
        except Exception as error:
            logging.error(f"DB add_topic failed: {error}")

    # ---------- thumbnail (image stored in DB, not kept in RAM) ----------

    def get_thumb_url(self):
        """URL of the thumbnail stored in DB (image data is NOT loaded)."""
        if not self.enabled:
            return None
        try:
            doc = self.meta.find_one({"_id": "thumbnail"}, {"url": 1})
            return doc.get("url") if doc else None
        except Exception as error:
            logging.error(f"DB get_thumb_url failed: {error}")
            return None

    def get_thumb_data(self):
        """Thumbnail bytes from DB. Caller should write to disk and drop them."""
        if not self.enabled:
            return None
        try:
            doc = self.meta.find_one({"_id": "thumbnail"}, {"data": 1})
            return bytes(doc["data"]) if doc and doc.get("data") else None
        except Exception as error:
            logging.error(f"DB get_thumb_data failed: {error}")
            return None

    def set_thumb(self, url, data):
        """Save/replace thumbnail. Old image in DB is overwritten (deleted)."""
        if not self.enabled:
            return
        if len(data) > 10 * 1024 * 1024:
            logging.warning("Thumbnail too large for DB, not stored.")
            return
        try:
            from bson.binary import Binary

            self.meta.replace_one(
                {"_id": "thumbnail"},
                {"_id": "thumbnail", "url": url, "data": Binary(data)},
                upsert=True,
            )
        except Exception as error:
            logging.error(f"DB set_thumb failed: {error}")
