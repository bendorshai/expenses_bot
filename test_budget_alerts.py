"""Tests for the daily budget-threshold alert feature (budget_alerts.py)."""
from unittest.mock import MagicMock, patch

import pytest

from budget_alerts import BudgetAlerter


def _alerter(fired_map=None):
    """Build a BudgetAlerter with a mocked MongoStorage.

    fired_map: {category_name: [already-fired thresholds]} — defaults to empty.
    """
    fired_map = fired_map or {}
    mongo = MagicMock()
    mongo.get_fired_thresholds.side_effect = (
        lambda year, month, category: list(fired_map.get(category, []))
    )
    alerter = BudgetAlerter(
        mongo_storage=mongo,
        chat_id=123,
        api_url="http://x/api/budget/status",
        api_token="secret",
    )
    return alerter, mongo


def _status(categories, year=2026, month=10):
    return {"ok": True, "year": year, "month": month, "categories": categories}


# ── compute_alerts: threshold logic ─────────────────────────────────

class TestComputeAlerts:
    def test_single_threshold_crossed(self):
        alerter, _ = _alerter()
        alerts = alerter.compute_alerts(_status([
            {"name": "מזון", "target": 1000.0, "spent": 510.0, "pct": 51.0},
        ]))
        assert len(alerts) == 1
        assert alerts[0]["category"] == "מזון"
        assert alerts[0]["threshold"] == 50
        assert alerts[0]["crossed"] == [50]

    def test_jump_crosses_two_reports_only_highest(self):
        """40% → 80% in one day crosses 50 and 75; report 75, mark both."""
        alerter, _ = _alerter()
        alerts = alerter.compute_alerts(_status([
            {"name": "מזון", "target": 1000.0, "spent": 800.0, "pct": 80.0},
        ]))
        assert len(alerts) == 1
        assert alerts[0]["threshold"] == 75
        assert alerts[0]["crossed"] == [50, 75]

    def test_already_fired_highest_not_reported_again(self):
        """Yesterday 51% fired [50]; today 65% — still highest-crossed is 50,
        already fired, so no new alert."""
        alerter, _ = _alerter(fired_map={"מזון": [50]})
        alerts = alerter.compute_alerts(_status([
            {"name": "מזון", "target": 1000.0, "spent": 650.0, "pct": 65.0},
        ]))
        assert alerts == []

    def test_next_threshold_after_fired_is_reported(self):
        """Yesterday fired [50]; today 75% — 75 is new, report it."""
        alerter, _ = _alerter(fired_map={"מזון": [50]})
        alerts = alerter.compute_alerts(_status([
            {"name": "מזון", "target": 1000.0, "spent": 760.0, "pct": 76.0},
        ]))
        assert len(alerts) == 1
        assert alerts[0]["threshold"] == 75

    def test_below_50_no_alert(self):
        alerter, _ = _alerter()
        alerts = alerter.compute_alerts(_status([
            {"name": "מזון", "target": 1000.0, "spent": 490.0, "pct": 49.0},
        ]))
        assert alerts == []

    def test_over_100_reported_once(self):
        alerter, _ = _alerter()
        alerts = alerter.compute_alerts(_status([
            {"name": "מזון", "target": 1000.0, "spent": 1200.0, "pct": 120.0},
        ]))
        assert len(alerts) == 1
        assert alerts[0]["threshold"] == 100
        assert alerts[0]["crossed"] == [50, 75, 100]

        # Once 100 is fired, nothing more fires.
        alerter2, _ = _alerter(fired_map={"מזון": [50, 75, 100]})
        assert alerter2.compute_alerts(_status([
            {"name": "מזון", "target": 1000.0, "spent": 1300.0, "pct": 130.0},
        ])) == []

    def test_unknown_category_starts_clean(self):
        """A category with no memory row behaves as never-fired."""
        alerter, mongo = _alerter()
        alerts = alerter.compute_alerts(_status([
            {"name": "קטגוריה-חדשה", "target": 500.0, "spent": 400.0, "pct": 80.0},
        ]))
        assert len(alerts) == 1
        assert alerts[0]["threshold"] == 75


# ── run: fetch + send + persist ─────────────────────────────────────

class TestRun:
    @pytest.mark.asyncio
    async def test_no_status_sends_nothing(self):
        alerter, mongo = _alerter()
        alerter.fetch_status = MagicMock(return_value=None)
        bot = MagicMock()
        bot.send_message = _AsyncRecorder()
        await alerter.run(bot)
        assert bot.send_message.calls == 0
        mongo.mark_thresholds_fired.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_alerts_sends_nothing(self):
        alerter, mongo = _alerter()
        alerter.fetch_status = MagicMock(return_value=_status([
            {"name": "מזון", "target": 1000.0, "spent": 100.0, "pct": 10.0},
        ]))
        bot = MagicMock()
        bot.send_message = _AsyncRecorder()
        await alerter.run(bot)
        assert bot.send_message.calls == 0
        mongo.mark_thresholds_fired.assert_not_called()

    @pytest.mark.asyncio
    async def test_alert_sends_message_and_marks(self):
        alerter, mongo = _alerter()
        alerter.fetch_status = MagicMock(return_value=_status([
            {"name": "מזון", "target": 1000.0, "spent": 800.0, "pct": 80.0},
        ]))
        bot = MagicMock()
        bot.send_message = _AsyncRecorder()
        await alerter.run(bot)
        assert bot.send_message.calls == 1
        assert bot.send_message.last_kwargs["chat_id"] == 123
        assert "מזון" in bot.send_message.last_kwargs["text"]
        mongo.mark_thresholds_fired.assert_called_once_with(2026, 10, "מזון", [50, 75])


class TestFetchStatus:
    def test_fetch_failure_returns_none(self):
        alerter, _ = _alerter()
        with patch("budget_alerts.requests.get", side_effect=OSError("boom")):
            assert alerter.fetch_status() is None

    def test_fetch_success_returns_json(self):
        alerter, _ = _alerter()
        resp = MagicMock()
        resp.json.return_value = {"ok": True, "categories": []}
        resp.raise_for_status.return_value = None
        with patch("budget_alerts.requests.get", return_value=resp) as g:
            out = alerter.fetch_status()
        assert out == {"ok": True, "categories": []}
        g.assert_called_once()


class TestBuildDiagnostic:
    def test_connection_failure_reported(self):
        alerter, _ = _alerter()
        alerter.fetch_status = MagicMock(return_value=None)
        report = alerter.build_diagnostic()
        assert "❌" in report
        assert alerter.api_url in report

    def test_ok_lists_categories_and_pct(self):
        alerter, _ = _alerter()
        alerter.fetch_status = MagicMock(return_value=_status([
            {"name": "מזון", "target": 1000.0, "spent": 510.0, "pct": 51.0},
            {"name": "תחבורה", "target": 500.0, "spent": 100.0, "pct": 20.0},
        ]))
        report = alerter.build_diagnostic()
        assert "✅" in report
        assert "מזון" in report and "51%" in report
        assert "תחבורה" in report
        # Highest-pct category listed first.
        assert report.index("מזון") < report.index("תחבורה")

    def test_ok_reports_would_fire(self):
        alerter, _ = _alerter()
        alerter.fetch_status = MagicMock(return_value=_status([
            {"name": "מזון", "target": 1000.0, "spent": 800.0, "pct": 80.0},
        ]))
        report = alerter.build_diagnostic()
        assert "🔔" in report
        assert "מזון" in report

    def test_ok_no_thresholds(self):
        alerter, _ = _alerter()
        alerter.fetch_status = MagicMock(return_value=_status([
            {"name": "מזון", "target": 1000.0, "spent": 100.0, "pct": 10.0},
        ]))
        report = alerter.build_diagnostic()
        assert "🔕" in report

    def test_diagnostic_does_not_mark_fired(self):
        """Running diagnostics must be read-only."""
        alerter, mongo = _alerter()
        alerter.fetch_status = MagicMock(return_value=_status([
            {"name": "מזון", "target": 1000.0, "spent": 800.0, "pct": 80.0},
        ]))
        alerter.build_diagnostic()
        mongo.mark_thresholds_fired.assert_not_called()


class _AsyncRecorder:
    """A minimal awaitable call recorder (MagicMock isn't awaitable)."""

    def __init__(self):
        self.calls = 0
        self.last_kwargs = None

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
