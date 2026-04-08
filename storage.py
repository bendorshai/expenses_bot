from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

from pymongo import MongoClient, DESCENDING

logger = logging.getLogger(__name__)

COLLECTION = "user_currencies"
ERROR_LOGS_COLLECTION = "error_logs"
ERROR_LOG_TTL_DAYS = 30


class MongoStorage:
    def __init__(self, uri: str, db_name: str):
        self._client = MongoClient(uri)
        self._db = self._client[db_name]
        self._col = self._db[COLLECTION]
        self._errors = self._db[ERROR_LOGS_COLLECTION]
        self._ensure_error_indexes()
        logger.info("MongoDB connected: %s / %s", uri.split("@")[-1], db_name)

    def _ensure_error_indexes(self) -> None:
        try:
            self._errors.create_index(
                "timestamp", expireAfterSeconds=ERROR_LOG_TTL_DAYS * 86400,
            )
        except Exception:
            logger.debug("Error log TTL index already exists or could not be created")

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

    # ------------------------------------------------------------------
    # Error logging
    # ------------------------------------------------------------------

    def log_error(
        self,
        error: BaseException | None = None,
        *,
        handler: str = "",
        chat_id: int | None = None,
        message_text: str = "",
        update_id: int | None = None,
    ) -> None:
        doc = {
            "timestamp": datetime.now(timezone.utc),
            "error_type": type(error).__name__ if error else "Unknown",
            "error_message": str(error) if error else "",
            "traceback": traceback.format_exception(error) if error else [],
            "handler": handler,
            "chat_id": chat_id,
            "message_text": message_text[:500] if message_text else "",
            "update_id": update_id,
        }
        try:
            self._errors.insert_one(doc)
        except Exception:
            logger.exception("Failed to log error to MongoDB")

    def get_recent_errors(self, limit: int = 50) -> list[dict]:
        return list(
            self._errors.find()
            .sort("timestamp", DESCENDING)
            .limit(limit)
        )
