"""TDD tests for migrating categories & directives to a remote config sheet.

Tests verify that:
- SheetsClient accepts a separate config_sheet_id
- get_categories() and get_directives() read from the config sheet
- append_directive() writes to the config sheet
- get_currencies() still reads from the expenses sheet
- main.py passes config_sheet_id from config to SheetsClient
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch, call
import pytest


EXPENSES_SHEET_ID = "expenses-sheet-id"
CONFIG_SHEET_ID = "config-sheet-id"
TABLE_COLUMNS = {"A": "תאריך", "C": "תיאור", "E": "חובה", "F": "זכות", "I": "תנועה", "J": "סיווג", "K": "מטבע"}


@pytest.fixture
def mock_gspread():
    """Patch Google auth and gspread so SheetsClient can be instantiated without credentials."""
    with patch("sheets.Credentials") as mock_creds, \
         patch("sheets.gspread") as mock_gs:
        mock_gc = MagicMock()
        mock_gs.authorize.return_value = mock_gc
        yield mock_gc


def _make_client(mock_gc, config_sheet_id=None):
    from sheets import SheetsClient
    kwargs = dict(
        credentials_file="fake.json",
        sheet_id=EXPENSES_SHEET_ID,
        tab_name="expenses",
        table_columns=TABLE_COLUMNS,
        categories_tab_name="categories",
        directives_tab_name="cash-directives",
        currencies_tab_name="currencies",
    )
    if config_sheet_id is not None:
        kwargs["config_sheet_id"] = config_sheet_id
    return SheetsClient(**kwargs)


# ---------- Constructor ----------

class TestConstructorAcceptsConfigSheetId:
    def test_with_config_sheet_id(self, mock_gspread):
        client = _make_client(mock_gspread, config_sheet_id=CONFIG_SHEET_ID)
        assert client.config_sheet_id == CONFIG_SHEET_ID

    def test_without_config_sheet_id_falls_back_to_sheet_id(self, mock_gspread):
        client = _make_client(mock_gspread, config_sheet_id=None)
        assert client.config_sheet_id == EXPENSES_SHEET_ID


# ---------- get_categories uses config sheet ----------

class TestGetCategoriesUsesConfigSheet:
    def test_opens_config_sheet_not_expenses_sheet(self, mock_gspread):
        client = _make_client(mock_gspread, config_sheet_id=CONFIG_SHEET_ID)

        config_spreadsheet = MagicMock()
        config_ws = MagicMock()
        config_ws.col_values.return_value = ["אוכל", "תחבורה", "בילויים"]
        config_spreadsheet.worksheet.return_value = config_ws

        mock_gspread.open_by_key.return_value = config_spreadsheet

        result = client.get_categories()

        mock_gspread.open_by_key.assert_called_with(CONFIG_SHEET_ID)
        config_spreadsheet.worksheet.assert_called_with("categories")
        assert result == ["אוכל", "תחבורה", "בילויים"]

    def test_does_not_touch_expenses_sheet(self, mock_gspread):
        client = _make_client(mock_gspread, config_sheet_id=CONFIG_SHEET_ID)

        config_spreadsheet = MagicMock()
        config_ws = MagicMock()
        config_ws.col_values.return_value = ["cat1"]
        config_spreadsheet.worksheet.return_value = config_ws
        mock_gspread.open_by_key.return_value = config_spreadsheet

        client.get_categories()

        # Should only be called with config sheet, never with expenses sheet
        calls = mock_gspread.open_by_key.call_args_list
        assert all(c == call(CONFIG_SHEET_ID) for c in calls)


# ---------- get_directives uses config sheet ----------

class TestGetDirectivesUsesConfigSheet:
    def test_opens_config_sheet_with_correct_tab_name(self, mock_gspread):
        client = _make_client(mock_gspread, config_sheet_id=CONFIG_SHEET_ID)

        config_spreadsheet = MagicMock()
        config_ws = MagicMock()
        config_ws.col_values.return_value = ["directive1", "directive2"]
        config_spreadsheet.worksheet.return_value = config_ws
        mock_gspread.open_by_key.return_value = config_spreadsheet

        result = client.get_directives()

        mock_gspread.open_by_key.assert_called_with(CONFIG_SHEET_ID)
        config_spreadsheet.worksheet.assert_called_with("cash-directives")
        assert result == ["directive1", "directive2"]


# ---------- append_directive uses config sheet ----------

class TestAppendDirectiveUsesConfigSheet:
    def test_appends_to_config_sheet(self, mock_gspread):
        client = _make_client(mock_gspread, config_sheet_id=CONFIG_SHEET_ID)

        config_spreadsheet = MagicMock()
        config_ws = MagicMock()
        config_spreadsheet.worksheet.return_value = config_ws
        mock_gspread.open_by_key.return_value = config_spreadsheet

        client.append_directive("new directive")

        mock_gspread.open_by_key.assert_called_with(CONFIG_SHEET_ID)
        config_spreadsheet.worksheet.assert_called_with("cash-directives")
        config_ws.append_row.assert_called_once_with(["new directive"], value_input_option="RAW")

    def test_does_not_write_to_expenses_sheet(self, mock_gspread):
        client = _make_client(mock_gspread, config_sheet_id=CONFIG_SHEET_ID)

        config_spreadsheet = MagicMock()
        config_ws = MagicMock()
        config_spreadsheet.worksheet.return_value = config_ws
        mock_gspread.open_by_key.return_value = config_spreadsheet

        client.append_directive("test")

        calls = mock_gspread.open_by_key.call_args_list
        assert all(c == call(CONFIG_SHEET_ID) for c in calls)


# ---------- get_currencies still uses expenses sheet ----------

class TestGetCurrenciesStaysLocal:
    def test_opens_expenses_sheet_not_config_sheet(self, mock_gspread):
        client = _make_client(mock_gspread, config_sheet_id=CONFIG_SHEET_ID)

        expenses_spreadsheet = MagicMock()
        currencies_ws = MagicMock()
        currencies_ws.col_values.return_value = ["שקל", "דולר", "אירו"]
        expenses_spreadsheet.worksheet.return_value = currencies_ws
        mock_gspread.open_by_key.return_value = expenses_spreadsheet

        result = client.get_currencies()

        mock_gspread.open_by_key.assert_called_with(EXPENSES_SHEET_ID)
        expenses_spreadsheet.worksheet.assert_called_with("currencies")
        assert result == ["שקל", "דולר", "אירו"]


# ---------- main.py config integration ----------

class TestMainPassesConfigSheetId:
    """Test that main.py extracts config_sheet_id from config and passes it to SheetsClient.

    We mock heavy imports (telegram, openai, pymongo) at sys.modules level
    so main.py can be imported without those packages installed.
    """

    @pytest.fixture(autouse=True)
    def _stub_heavy_imports(self):
        """Stub out modules that aren't installed in the test environment."""
        stubs = {}
        for mod_name in [
            "telegram", "telegram.ext", "telegram.constants",
            "openai", "pymongo",
            "bot", "categorizer", "storage",
            "handlers", "handlers.base", "handlers.edit_handlers",
            "handlers.menu_handlers", "handlers.insights_handlers", "handlers.utils",
            "parsing", "keyboards",
        ]:
            if mod_name not in sys.modules:
                stubs[mod_name] = MagicMock()
        with patch.dict(sys.modules, stubs):
            # Force reimport of main so it picks up stubs
            if "main" in sys.modules:
                del sys.modules["main"]
            yield
            if "main" in sys.modules:
                del sys.modules["main"]

    def test_config_sheet_id_passed_to_sheets_client(self):
        cfg = {
            "telegram": {"bot_token": "tok", "chat_id": 123},
            "openai": {"api_key": "sk-test"},
            "google_sheets": {
                "credentials_file": "creds.json",
                "sheet_id": EXPENSES_SHEET_ID,
                "config_sheet_id": CONFIG_SHEET_ID,
                "tab_name": "expenses",
                "categories_tab_name": "categories",
                "directives_tab_name": "cash-directives",
                "currencies_tab_name": "currencies",
            },
            "mongodb": {"uri": "mongodb://localhost", "db_name": "test"},
            "table_columns": TABLE_COLUMNS,
        }

        with patch("main.load_config", return_value=cfg), \
             patch("main.SheetsClient") as MockSheets, \
             patch("main.Categorizer"), \
             patch("main.MongoStorage"), \
             patch("main.create_bot") as mock_bot:

            mock_client = MagicMock()
            mock_client.get_currencies.return_value = ["שקל"]
            MockSheets.return_value = mock_client
            mock_app = MagicMock()
            mock_bot.return_value = mock_app
            mock_app.run_polling = MagicMock(side_effect=SystemExit)

            try:
                from main import main
                main()
            except SystemExit:
                pass

            MockSheets.assert_called_once()
            call_kwargs = MockSheets.call_args[1]
            assert call_kwargs["config_sheet_id"] == CONFIG_SHEET_ID

    def test_missing_config_sheet_id_passes_none(self):
        cfg = {
            "telegram": {"bot_token": "tok", "chat_id": 123},
            "openai": {"api_key": "sk-test"},
            "google_sheets": {
                "credentials_file": "creds.json",
                "sheet_id": EXPENSES_SHEET_ID,
                "tab_name": "expenses",
            },
            "mongodb": {"uri": "mongodb://localhost", "db_name": "test"},
            "table_columns": TABLE_COLUMNS,
        }

        with patch("main.load_config", return_value=cfg), \
             patch("main.SheetsClient") as MockSheets, \
             patch("main.Categorizer"), \
             patch("main.MongoStorage"), \
             patch("main.create_bot") as mock_bot:

            mock_client = MagicMock()
            mock_client.get_currencies.return_value = ["שקל"]
            MockSheets.return_value = mock_client
            mock_app = MagicMock()
            mock_bot.return_value = mock_app
            mock_app.run_polling = MagicMock(side_effect=SystemExit)

            try:
                from main import main
                main()
            except SystemExit:
                pass

            MockSheets.assert_called_once()
            call_kwargs = MockSheets.call_args[1]
            assert call_kwargs.get("config_sheet_id") is None
