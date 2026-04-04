from __future__ import annotations

import logging

from pymongo import MongoClient

logger = logging.getLogger(__name__)

COLLECTION = "user_currencies"


class MongoStorage:
    def __init__(self, uri: str, db_name: str):
        self._client = MongoClient(uri)
        self._db = self._client[db_name]
        self._col = self._db[COLLECTION]
        logger.info("MongoDB connected: %s / %s", uri.split("@")[-1], db_name)

    def get_user_currency(self, user_id: int) -> str | None:
        doc = self._col.find_one({"_id": user_id})
        return doc["currency"] if doc else None

    def set_user_currency(self, user_id: int, currency: str) -> None:
        self._col.update_one(
            {"_id": user_id},
            {"$set": {"currency": currency}},
            upsert=True,
        )

    def get_all_user_currencies(self) -> dict[int, str]:
        return {doc["_id"]: doc["currency"] for doc in self._col.find()}
