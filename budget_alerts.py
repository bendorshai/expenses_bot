"""Daily budget-threshold alerts.

Once a day the bot asks the card_to_sheet system (via its token-protected
/api/budget/status endpoint) for each expense category's monthly budget target
and current spend. For every category it sends a Telegram alert the first time
usage crosses 50%, 75% or 100% in a given month — each threshold fires once.

Memory lives in MongoDB (MongoStorage.budget_alerts), keyed by
(year, month, category name). Because we only ever look up categories the API
returns right now, categories that are added / merged / renamed / deleted in the
sheet never corrupt the state: a new name starts clean, a gone name is simply
never queried.
"""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

THRESHOLDS = (50, 75, 100)
_EMOJI = {50: "🟡", 75: "🟠", 100: "🔴"}
_MONTHS_HE = [
    "", "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר",
]


class BudgetAlerter:
    def __init__(self, mongo_storage, chat_id: int, api_url: str, api_token: str):
        self.mongo = mongo_storage
        self.chat_id = chat_id
        self.api_url = api_url
        self.api_token = api_token

    # ------------------------------------------------------------------

    def fetch_status(self) -> dict | None:
        """GET the current-month budget status; None on any failure (never raises)."""
        try:
            resp = requests.get(
                self.api_url, params={"token": self.api_token}, timeout=30
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.warning("Budget status fetch failed", exc_info=True)
            return None

    def compute_alerts(self, status: dict) -> list[dict]:
        """Return the alerts to send — one per category whose highest newly
        crossed threshold hasn't fired yet this month.

        Each alert dict: {category, pct, spent, target, threshold, crossed},
        where `threshold` is the highest crossed tier (the one we announce) and
        `crossed` is every tier at/under current usage (all get marked fired).
        """
        year = status["year"]
        month = status["month"]
        alerts: list[dict] = []
        for c in status.get("categories", []):
            pct = c["pct"]
            crossed = [t for t in THRESHOLDS if pct >= t]
            if not crossed:
                continue
            highest = max(crossed)
            fired = self.mongo.get_fired_thresholds(year, month, c["name"])
            if highest in fired:
                continue
            alerts.append({
                "category": c["name"],
                "pct": pct,
                "spent": c["spent"],
                "target": c["target"],
                "threshold": highest,
                "crossed": crossed,
            })
        return alerts

    def format_message(self, alerts: list[dict], year: int, month: int) -> str:
        month_name = _MONTHS_HE[month] if 1 <= month <= 12 else str(month)
        lines = [f"📊 התראת תקציב — {month_name} {year}", ""]
        for a in sorted(alerts, key=lambda x: x["threshold"], reverse=True):
            emoji = _EMOJI.get(a["threshold"], "⚠️")
            lines.append(
                f"{emoji} {a['category']}: {a['pct']:.0f}% מהתקציב "
                f"(₪{a['spent']:,.0f} מתוך ₪{a['target']:,.0f})"
            )
        return "\n".join(lines)

    async def run(self, bot) -> None:
        """Fetch → compute → (if any) send one message and persist the fired
        thresholds. Nothing is sent when no threshold is newly crossed."""
        status = self.fetch_status()
        if not status or not status.get("ok"):
            return
        alerts = self.compute_alerts(status)
        if not alerts:
            return

        text = self.format_message(alerts, status["year"], status["month"])
        # Send first, persist second: a failed send retries tomorrow rather than
        # being silently swallowed by already-marked memory.
        await bot.send_message(chat_id=self.chat_id, text=text)
        for a in alerts:
            self.mongo.mark_thresholds_fired(
                status["year"], status["month"], a["category"], a["crossed"]
            )
