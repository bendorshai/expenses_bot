"""TDD tests for menu-driven income (הכנסה) entry.

Income is a deterministic, menu-driven flow (no GPT):
- A "➕ הוסף הכנסה" button in the main menu starts a two-step flow (description, amount).
- Income rows go to the credit column: חובה=0, זכות=amount, תנועה=+amount, category "אחר".
"""

from __future__ import annotations

import sys
import time
from unittest.mock import MagicMock, AsyncMock, patch
import pytest


# ---------- append_expense income semantics ----------

class TestAppendExpenseIncome:
    """append_expense(kind="income") must write to זכות; expense stays on חובה."""

    def _client(self):
        from sheets import SheetsClient
        client = SheetsClient.__new__(SheetsClient)  # bypass gspread auth
        client.table_columns = {
            "A": "תאריך", "C": "תיאור", "E": "חובה", "F": "זכות",
            "G": "מאזן", "I": "תנועה", "J": "סיווג", "K": "מטבע", "L": "מבצע",
        }
        client.total_cols = 12
        client.tab_name = "expenses"
        ws = MagicMock()
        ws.append_row.return_value = {"updates": {"updatedRange": "expenses!A7:L7"}}
        client._get_worksheet = MagicMock(return_value=ws)
        return client, ws

    def _row(self, ws):
        return ws.append_row.call_args[0][0]

    def test_income_goes_to_credit_column(self):
        client, ws = self._client()
        row = client.append_expense(amount=250.0, description="משכורת", currency="שקל", kind="income")
        assert row == 7
        r = self._row(ws)
        assert r[4] == "0"          # חובה
        assert r[5] == "250.0"      # זכות
        assert r[8] == "250.0"      # תנועה (positive)

    def test_expense_unchanged(self):
        client, ws = self._client()
        client.append_expense(amount=250.0, description="חלב", currency="שקל")
        r = self._row(ws)
        assert r[4] == "250.0"      # חובה
        assert r[5] == "0"          # זכות
        assert r[8] == "-250.0"     # תנועה (negative)

    def test_income_with_performer(self):
        client, ws = self._client()
        client.append_expense(amount=10.0, description="x", currency="שקל",
                              kind="income", performer="@shai")
        r = self._row(ws)
        assert r[11] == "@shai"     # מבצע


# ---------- income two-step flow ----------

def _handler_stubs():
    stubs = {}
    for mod_name in [
        "telegram", "telegram.ext", "telegram.constants",
        "openai", "pymongo", "bot", "storage", "parsing", "keyboards",
    ]:
        if mod_name not in sys.modules:
            stubs[mod_name] = MagicMock()
    return stubs


def _clean_handler_modules():
    for m in ["handlers", "handlers.base", "handlers.edit_handlers",
              "handlers.menu_handlers", "handlers.insights_handlers", "handlers.utils",
              "categorizer"]:
        if m in sys.modules:
            del sys.modules[m]


class TestIncomeFlow:
    @pytest.fixture(autouse=True)
    def _stub_imports(self):
        stubs = _handler_stubs()
        with patch.dict(sys.modules, stubs):
            _clean_handler_modules()
            yield
            _clean_handler_modules()

    def _make_handler(self):
        from handlers.base import ExpenseHandlers
        handler = MagicMock(spec=ExpenseHandlers)
        handler.chat_id = 123
        handler.default_currency = "שקל"
        handler.sheets = MagicMock()
        handler.sheets.append_expense.return_value = 7
        handler._get_user_currency = MagicMock(return_value="שקל")
        return handler

    def _ctx(self, pending):
        context = MagicMock()
        context.chat_data = {"pending_income": pending}
        context.bot.edit_message_text = AsyncMock()
        return context

    def _msg(self, text):
        message = MagicMock()
        message.text = text
        message.chat_id = 123
        message.from_user.id = 1
        message.set_reaction = AsyncMock()
        return message

    @pytest.mark.asyncio
    async def test_description_step_advances_to_amount(self):
        from handlers.base import ExpenseHandlers
        handler = self._make_handler()
        handler._handle_pending_income = ExpenseHandlers._handle_pending_income.__get__(handler, ExpenseHandlers)
        context = self._ctx({"step": "description", "bot_message_id": 10, "timestamp": time.time()})
        message = self._msg("משכורת")

        with patch("handlers.base.safe_react", new_callable=AsyncMock):
            handled = await handler._handle_pending_income(message, context)

        assert handled is True
        assert context.chat_data["pending_income"]["step"] == "amount"
        assert context.chat_data["pending_income"]["description"] == "משכורת"
        handler.sheets.append_expense.assert_not_called()

    @pytest.mark.asyncio
    async def test_amount_step_records_income(self):
        from handlers.base import ExpenseHandlers
        handler = self._make_handler()
        handler._handle_pending_income = ExpenseHandlers._handle_pending_income.__get__(handler, ExpenseHandlers)
        context = self._ctx({"step": "amount", "description": "משכורת",
                             "bot_message_id": 10, "timestamp": time.time()})
        message = self._msg("5000")

        with patch("handlers.base.safe_react", new_callable=AsyncMock):
            handled = await handler._handle_pending_income(message, context)

        assert handled is True
        handler.sheets.append_expense.assert_called_once()
        kwargs = handler.sheets.append_expense.call_args.kwargs
        assert kwargs.get("kind") == "income"
        assert kwargs.get("amount") == 5000.0
        assert kwargs.get("description") == "משכורת"
        # category recorded as "אחר"
        handler.sheets.update_category.assert_called_once()
        assert handler.sheets.update_category.call_args[0][1] == "אחר"
        # flow cleared
        assert "pending_income" not in context.chat_data

    @pytest.mark.asyncio
    async def test_invalid_amount_reprompts(self):
        from handlers.base import ExpenseHandlers
        handler = self._make_handler()
        handler._handle_pending_income = ExpenseHandlers._handle_pending_income.__get__(handler, ExpenseHandlers)
        context = self._ctx({"step": "amount", "description": "משכורת",
                             "bot_message_id": 10, "timestamp": time.time()})
        message = self._msg("לא מספר")

        with patch("handlers.base.safe_react", new_callable=AsyncMock):
            handled = await handler._handle_pending_income(message, context)

        assert handled is True
        handler.sheets.append_expense.assert_not_called()
        assert context.chat_data["pending_income"]["step"] == "amount"


# ---------- menu button presence ----------

class TestIncomeMenuButton:
    def test_main_menu_has_income_button(self):
        # Real keyboards (telegram installed) — assert the income button exists.
        for m in list(sys.modules):
            if m == "keyboards":
                del sys.modules[m]
        import keyboards
        markup = keyboards.make_main_menu_keyboard()
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert any(c.endswith("income") for c in callbacks)
