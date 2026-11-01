"""TDD tests for deterministic exact-match categorization of expenses.

When a parsed expense description contains "(X)" where X is an EXACT category name,
_record_and_confirm assigns it directly (no "אחר", no confirmation prompt). Otherwise
it keeps the existing behavior: record "אחר" and ask to confirm GPT's suggestion.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, AsyncMock, patch
import pytest


def _handler_stubs():
    """Stub heavy imports but keep `parsing` and `categorizer` real."""
    stubs = {}
    for mod_name in [
        "telegram", "telegram.ext", "telegram.constants",
        "openai", "pymongo", "bot", "storage", "keyboards",
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


class TestExpenseExactMatch:
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
        handler._categories = ["אוכל בחוץ", "קניות", "אחר"]
        handler.sheets = MagicMock()
        handler.sheets.append_expense.return_value = 7
        handler._record_and_confirm = ExpenseHandlers._record_and_confirm.__get__(handler, ExpenseHandlers)
        return handler

    def _expense(self, description, category):
        from categorizer import ParsedExpense
        return ParsedExpense(amount=55.0, description=description, category=category,
                             currency="שקל", date=None)

    def _reply_target(self):
        target = MagicMock()
        target.reply_text = AsyncMock(return_value=MagicMock(message_id=100))
        return target

    @pytest.mark.asyncio
    async def test_exact_match_assigns_directly_without_prompt(self):
        handler = self._make_handler()
        target = self._reply_target()
        expenses = [self._expense("שווארמה (אוכל בחוץ)", "אוכל")]  # GPT guessed "אוכל"

        await handler._record_and_confirm(expenses, MagicMock(), target, {})

        # category recorded as the exact match, not "אחר"
        handler.sheets.update_category.assert_called_once_with(7, "אוכל בחוץ")
        # only the ack message is sent — no "💡 לסווג..." confirmation prompt
        assert target.reply_text.call_count == 1

    @pytest.mark.asyncio
    async def test_non_exact_falls_back_to_suggestion_prompt(self):
        handler = self._make_handler()
        target = self._reply_target()
        expenses = [self._expense("קפה (טעים)", "אוכל בחוץ")]  # "(טעים)" is not a category

        await handler._record_and_confirm(expenses, MagicMock(), target, {})

        # recorded "אחר", GPT suggestion kept for confirmation
        handler.sheets.update_category.assert_called_once_with(7, "אחר")
        # ack + one confirmation prompt
        assert target.reply_text.call_count == 2
