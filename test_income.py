"""TDD tests for the redesigned income (הכנסה) entry.

Income is a single-message, GPT-parsed flow:
- "➕ הוסף הכנסה" asks for everything in one message (description, amount, currency,
  preferred category); the message is parsed by GPT (parse_income).
- The row is recorded immediately as income (חובה=0, זכות=amount, תנועה=+amount),
  category left "אחר" — then the bot shows all parsed fields + the suggested category
  and asks to confirm.
- ✅ applies the suggested category; ❌ starts a free-text correction loop.
- Editing an income amount must stay on the credit column (kind-aware update_amount).
"""

from __future__ import annotations

import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch, call
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


# ---------- kind-aware update_amount ----------

class TestUpdateAmountKind:
    """Editing an amount must target the correct double-entry column for the row's kind."""

    def _client(self):
        from sheets import SheetsClient
        client = SheetsClient.__new__(SheetsClient)
        client.table_columns = {
            "A": "תאריך", "C": "תיאור", "E": "חובה", "F": "זכות",
            "G": "מאזן", "I": "תנועה", "J": "סיווג", "K": "מטבע", "L": "מבצע",
        }
        client.total_cols = 12
        client.update_cell_by_name = MagicMock()
        return client

    def _set_row(self, client, debit, credit):
        # columns by 0-based index: E=4 (חובה), F=5 (זכות), I=8 (תנועה)
        row = ["01/01/2026", "", "desc", "", debit, credit, "", "", credit or debit,
               "אחר", "שקל", "@x"]
        ws = MagicMock()
        ws.row_values.return_value = row
        client._get_worksheet = MagicMock(return_value=ws)

    def test_income_amount_updates_credit(self):
        client = self._client()
        self._set_row(client, debit="0", credit="250")
        client.update_amount(7, 300)
        calls = client.update_cell_by_name.call_args_list
        assert call(7, "זכות", "300") in calls
        assert call(7, "תנועה", "300") in calls

    def test_expense_amount_updates_debit(self):
        client = self._client()
        self._set_row(client, debit="250", credit="0")
        client.update_amount(7, 300)
        calls = client.update_cell_by_name.call_args_list
        assert call(7, "חובה", "300") in calls
        assert call(7, "תנועה", "-300") in calls


# ---------- income single-message flow ----------

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
        handler._categories = ["הכנסה קבועה", "אחר"]
        handler.currency_list = ["שקל", "דולר"]
        handler.sheets = MagicMock()
        handler.sheets.append_expense.return_value = 7
        handler._get_user_currency = MagicMock(return_value="שקל")
        return handler

    def _bind(self, handler, *names):
        from handlers.base import ExpenseHandlers
        for name in names:
            setattr(handler, name, getattr(ExpenseHandlers, name).__get__(handler, ExpenseHandlers))

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
        message.from_user.username = "shai"
        message.set_reaction = AsyncMock()
        return message

    @pytest.mark.asyncio
    async def test_collect_parses_records_and_confirms(self):
        handler = self._make_handler()
        self._bind(handler, "_handle_pending_income", "_show_income_confirmation",
                   "_income_confirmation_keyboard")
        handler.categorizer = MagicMock()
        handler.categorizer.parse_income.return_value = SimpleNamespace(
            amount=5000.0, description="משכורת", category="הכנסה קבועה", currency="דולר")
        context = self._ctx({"phase": "collect", "bot_message_id": 10, "timestamp": time.time()})
        message = self._msg("משכורת 5000 דולר (הכנסה קבועה)")

        with patch("handlers.base.safe_react", new_callable=AsyncMock):
            handled = await handler._handle_pending_income(message, context)

        assert handled is True
        handler.categorizer.parse_income.assert_called_once()
        kwargs = handler.sheets.append_expense.call_args.kwargs
        assert kwargs.get("kind") == "income"
        assert kwargs.get("amount") == 5000.0
        assert kwargs.get("description") == "משכורת"
        assert kwargs.get("currency") == "דולר"
        # recorded as "אחר" first
        assert handler.sheets.update_category.call_args[0][1] == "אחר"
        # advanced to confirm, storing the suggested category
        p = context.chat_data["pending_income"]
        assert p["phase"] == "confirm"
        assert p["suggested_category"] == "הכנסה קבועה"
        assert p["row_number"] == 7

    @pytest.mark.asyncio
    async def test_unparseable_reprompts_without_recording(self):
        handler = self._make_handler()
        self._bind(handler, "_handle_pending_income")
        handler.categorizer = MagicMock()
        handler.categorizer.parse_income.return_value = None
        context = self._ctx({"phase": "collect", "bot_message_id": 10, "timestamp": time.time()})
        message = self._msg("בלה בלה")

        with patch("handlers.base.safe_react", new_callable=AsyncMock):
            handled = await handler._handle_pending_income(message, context)

        assert handled is True
        handler.sheets.append_expense.assert_not_called()
        assert context.chat_data["pending_income"]["phase"] == "collect"

    @pytest.mark.asyncio
    async def test_confirm_phase_does_not_consume_text(self):
        handler = self._make_handler()
        self._bind(handler, "_handle_pending_income")
        context = self._ctx({"phase": "confirm", "bot_message_id": 10, "row_number": 7,
                             "timestamp": time.time()})
        message = self._msg("חלב 10")

        with patch("handlers.base.safe_react", new_callable=AsyncMock):
            handled = await handler._handle_pending_income(message, context)

        assert handled is False  # falls through to normal expense handling

    @pytest.mark.asyncio
    async def test_fix_phase_applies_correction(self):
        handler = self._make_handler()
        self._bind(handler, "_handle_pending_income", "_show_income_confirmation",
                   "_income_confirmation_keyboard")
        handler.categorizer = MagicMock()
        handler.categorizer.parse_income.return_value = SimpleNamespace(
            amount=1200.0, description="משכורת", category="הכנסה קבועה", currency="דולר")
        context = self._ctx({
            "phase": "fix", "bot_message_id": 10, "row_number": 7,
            "description": "משכורת", "amount": 1000.0, "currency": "דולר",
            "suggested_category": "הכנסה קבועה", "timestamp": time.time(),
        })
        message = self._msg("הסכום הוא 1200")

        with patch("handlers.base.safe_react", new_callable=AsyncMock):
            handled = await handler._handle_pending_income(message, context)

        assert handled is True
        # correction routed through GPT with the current state
        assert handler.categorizer.parse_income.call_args.kwargs.get("current") is not None
        handler.sheets.update_amount.assert_called_once_with(7, 1200.0)
        assert context.chat_data["pending_income"]["phase"] == "confirm"
        assert context.chat_data["pending_income"]["amount"] == 1200.0


# ---------- confirm / reject callbacks ----------

class TestIncomeConfirmReject:
    @pytest.fixture(autouse=True)
    def _stub_imports(self):
        # Keep `keyboards` real so the callback-prefix constants are genuine strings
        # (the handlers do str.removeprefix on them).
        stubs = {}
        for mod_name in ["telegram", "telegram.ext", "telegram.constants",
                         "openai", "pymongo", "bot", "storage", "parsing"]:
            if mod_name not in sys.modules:
                stubs[mod_name] = MagicMock()
        if "keyboards" in sys.modules:
            del sys.modules["keyboards"]
        with patch.dict(sys.modules, stubs):
            _clean_handler_modules()
            yield
            _clean_handler_modules()

    def _make_handler(self):
        from handlers.base import ExpenseHandlers
        handler = MagicMock(spec=ExpenseHandlers)
        handler.sheets = MagicMock()
        return handler

    def _bind(self, handler, name):
        from handlers.base import ExpenseHandlers
        setattr(handler, name, getattr(ExpenseHandlers, name).__get__(handler, ExpenseHandlers))

    def _query(self, data):
        query = MagicMock()
        query.data = data
        query.message.message_id = 10
        query.message.text = "📝 הכנסה נקלטה:\nתיאור: משכורת\n\nהפרטים נכונים?"
        query.edit_message_text = AsyncMock()
        return query

    @pytest.mark.asyncio
    async def test_confirm_applies_suggested_category(self):
        handler = self._make_handler()
        self._bind(handler, "handle_income_confirm")
        context = MagicMock()
        context.chat_data = {"pending_income": {
            "row_number": 7, "description": "משכורת", "amount": 5000.0,
            "currency": "דולר", "suggested_category": "הכנסה קבועה",
        }}
        update = MagicMock()
        update.callback_query = self._query("incok_7")

        with patch("handlers.edit_handlers.safe_answer", new_callable=AsyncMock):
            await handler.handle_income_confirm(update, context)

        handler.sheets.update_category.assert_called_once_with(7, "הכנסה קבועה")
        assert "pending_income" not in context.chat_data

    @pytest.mark.asyncio
    async def test_reject_enters_fix_phase(self):
        handler = self._make_handler()
        self._bind(handler, "handle_income_reject")
        context = MagicMock()
        context.chat_data = {"pending_income": {
            "row_number": 7, "description": "משכורת", "amount": 5000.0,
            "currency": "דולר", "suggested_category": "הכנסה קבועה",
        }}
        update = MagicMock()
        update.callback_query = self._query("incno_7")

        with patch("handlers.edit_handlers.safe_answer", new_callable=AsyncMock):
            await handler.handle_income_reject(update, context)

        assert context.chat_data["pending_income"]["phase"] == "fix"
        handler.sheets.update_category.assert_not_called()


# ---------- menu button presence ----------

class TestIncomeMenuButton:
    def test_main_menu_has_income_button(self):
        for m in list(sys.modules):
            if m == "keyboards":
                del sys.modules[m]
        import keyboards
        markup = keyboards.make_main_menu_keyboard()
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert any(c.endswith("income") for c in callbacks)
