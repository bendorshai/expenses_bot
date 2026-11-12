"""TDD tests: sheet update/delete methods return the previous value.

The edit-notice feature needs the OLD value for every change. Rather than making
each handler re-read the row, the sheets layer returns what it replaced.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

TABLE_COLUMNS = {
    "A": "תאריך", "C": "תיאור", "E": "חובה", "F": "זכות",
    "I": "תנועה", "J": "סיווג", "K": "מטבע",
}


@pytest.fixture
def client():
    with patch("sheets.Credentials"), patch("sheets.gspread") as mock_gs:
        mock_gs.authorize.return_value = MagicMock()
        from sheets import SheetsClient
        c = SheetsClient(
            credentials_file="fake.json",
            sheet_id="sid",
            tab_name="expenses",
            table_columns=TABLE_COLUMNS,
        )
        yield c


def _ws_with_cell(old_value):
    ws = MagicMock()
    ws.acell.return_value = MagicMock(value=old_value)
    return ws


class TestNamedCellReturnsOld:
    def test_update_description_returns_old(self, client):
        ws = _ws_with_cell("חלב")
        with patch.object(client, "_get_worksheet", return_value=ws):
            assert client.update_description(5, "גבינה") == "חלב"
        ws.update_acell.assert_called_once()

    def test_update_currency_returns_old(self, client):
        ws = _ws_with_cell("שקל")
        with patch.object(client, "_get_worksheet", return_value=ws):
            assert client.update_currency(5, "דולר") == "שקל"

    def test_update_category_returns_old(self, client):
        ws = _ws_with_cell("אחר")
        with patch.object(client, "_get_worksheet", return_value=ws):
            assert client.update_category(5, "אוכל") == "אחר"

    def test_missing_old_value_returns_empty_string(self, client):
        ws = _ws_with_cell(None)
        with patch.object(client, "_get_worksheet", return_value=ws):
            assert client.update_description(5, "x") == ""

    def test_update_date_returns_old(self, client):
        ws = _ws_with_cell("01/01/2026")
        with patch.object(client, "_get_worksheet", return_value=ws):
            assert client.update_date(5, date(2026, 2, 3)) == "01/01/2026"
        ws.update_acell.assert_called_once()


class TestUpdateAmountReturnsOld:
    def test_expense_returns_old_debit(self, client):
        ws = MagicMock()
        data = {"חובה": "30", "זכות": "0"}
        with patch.object(client, "_get_worksheet", return_value=ws), \
             patch.object(client, "get_expense_data", return_value=data):
            assert client.update_amount(5, 50.0) == 30.0

    def test_income_returns_old_credit(self, client):
        ws = MagicMock()
        data = {"חובה": "0", "זכות": "1000"}
        with patch.object(client, "_get_worksheet", return_value=ws), \
             patch.object(client, "get_expense_data", return_value=data):
            assert client.update_amount(5, 1500.0) == 1000.0


class TestDeleteReturnsRecord:
    def test_delete_returns_record(self, client):
        ws = MagicMock()
        record = {"תיאור": "חלב", "חובה": "15", "זכות": "0", "מטבע": "שקל"}
        with patch.object(client, "_get_worksheet", return_value=ws), \
             patch.object(client, "get_expense_data", return_value=record):
            assert client.delete_row(5) == record
        ws.update.assert_called_once()
