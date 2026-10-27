"""TDD tests for fallback expense extraction and unknown-message handling.

Tests verify that:
- _try_fallback_expense extracts amount + description from raw text
- handle_message records a fallback expense when GPT returns 'unknown' but text has a number
- handle_message silently ignores when GPT returns 'unknown' and text has no number
- The GPT system prompt contains a strong brackets-as-category override rule
- The GPT system prompt contains a 'prefer expenses' rule for messages with numbers
"""

from __future__ import annotations

import re
import sys
from unittest.mock import MagicMock, AsyncMock, patch, call
import pytest


# ---------- Fallback extraction tests ----------

def _handler_stubs():
    """Return dict of stubs for heavy imports, keeping categorizer real (only openai mocked)."""
    stubs = {}
    for mod_name in [
        "telegram", "telegram.ext", "telegram.constants",
        "openai", "pymongo",
        "bot", "storage",
        "parsing", "keyboards",
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


class TestTryFallbackExpense:
    """Test the _try_fallback_expense static/helper that extracts amount from raw text."""

    @pytest.fixture(autouse=True)
    def _stub_imports(self):
        stubs = _handler_stubs()
        with patch.dict(sys.modules, stubs):
            _clean_handler_modules()
            yield
            _clean_handler_modules()

    def _get_fallback_fn(self):
        from handlers.base import ExpenseHandlers
        return ExpenseHandlers._try_fallback_expense

    def test_number_after_text(self):
        result = self._get_fallback_fn()("קפה 50", "שקל")
        assert result is not None
        assert result.amount == 50.0
        assert "קפה" in result.description
        assert result.category == "אחר"
        assert result.currency == "שקל"

    def test_number_before_text(self):
        result = self._get_fallback_fn()("50 קפה", "שקל")
        assert result is not None
        assert result.amount == 50.0
        assert "קפה" in result.description
        assert result.category == "אחר"

    def test_decimal_number(self):
        result = self._get_fallback_fn()("25.5 ביצים", "דולר")
        assert result is not None
        assert result.amount == 25.5
        assert "ביצים" in result.description
        assert result.currency == "דולר"

    def test_no_number_returns_none(self):
        result = self._get_fallback_fn()("hello world", "שקל")
        assert result is None

    def test_preserves_full_description_minus_amount(self):
        result = self._get_fallback_fn()("מונית 20 (טיסות)", "שקל")
        assert result is not None
        assert result.amount == 20.0
        assert "מונית" in result.description
        assert "(טיסות)" in result.description

    def test_only_number_gives_empty_description(self):
        result = self._get_fallback_fn()("50", "שקל")
        assert result is not None
        assert result.amount == 50.0
        assert result.category == "אחר"


# ---------- handle_message fallback integration tests ----------

class TestHandleMessageFallback:
    """When GPT returns 'unknown' but text has a number, expense should be recorded as אחר."""

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
        handler._categories = ["אוכל", "תחבורה", "אחר"]
        handler._directives = []
        handler._popular_categories = []
        handler.currency_list = ["שקל"]
        handler.default_currency = "שקל"
        handler.currency_lookup = {}
        handler.sheets = MagicMock()
        handler.sheets.append_expense.return_value = 5
        handler.categorizer = MagicMock()
        handler.mongo = MagicMock()
        return handler

    @pytest.mark.asyncio
    async def test_unknown_with_number_records_expense(self):
        from handlers.base import ExpenseHandlers
        from categorizer import ParseResult

        handler = self._make_handler()
        handler.categorizer.parse_message.return_value = ParseResult(type="unknown")
        handler._handle_reply_edit = AsyncMock(return_value=False)
        handler._handle_pending_question = AsyncMock(return_value=False)
        handler._handle_pending_edit = AsyncMock(return_value=False)
        handler._get_user_currency = MagicMock(return_value="שקל")
        handler._try_fallback_expense = ExpenseHandlers._try_fallback_expense
        # Bind the real record-and-confirm helper (handle_message delegates to it).
        handler._record_and_confirm = ExpenseHandlers._record_and_confirm.__get__(handler, ExpenseHandlers)

        message = MagicMock()
        message.text = "קפה 30"
        message.chat_id = 123
        message.from_user.id = 1
        message.set_reaction = AsyncMock()
        message.reply_text = AsyncMock()

        update = MagicMock()
        update.effective_message = message

        context = MagicMock()
        context.chat_data = {}

        # Stub parsing.israel_today
        with patch("handlers.base.israel_today") as mock_today, \
             patch("handlers.base.detect_mode_change", return_value=None), \
             patch("handlers.base.safe_react", new_callable=AsyncMock), \
             patch("handlers.base.is_edit_request", return_value=False):
            import datetime
            mock_today.return_value = datetime.date(2026, 5, 5)

            await ExpenseHandlers.handle_message(handler, update, context)

        # Expense should have been appended
        handler.sheets.append_expense.assert_called_once()
        call_kwargs = handler.sheets.append_expense.call_args
        # Category should be אחר (always recorded as "other")
        handler.sheets.update_category.assert_called_once()
        cat_arg = handler.sheets.update_category.call_args[0][1]
        assert cat_arg == "אחר"
        # Should have replied with the acknowledgment (fallback suggestion is אחר -> no confirm msg)
        message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_without_number_silently_ignored(self):
        from handlers.base import ExpenseHandlers
        from categorizer import ParseResult

        handler = self._make_handler()
        handler.categorizer.parse_message.return_value = ParseResult(type="unknown")
        handler._handle_reply_edit = AsyncMock(return_value=False)
        handler._handle_pending_question = AsyncMock(return_value=False)
        handler._handle_pending_edit = AsyncMock(return_value=False)
        handler._get_user_currency = MagicMock(return_value="שקל")

        message = MagicMock()
        message.text = "שלום עולם"  # no number
        message.chat_id = 123
        message.from_user.id = 1
        message.set_reaction = AsyncMock()
        message.reply_text = AsyncMock()

        update = MagicMock()
        update.effective_message = message

        context = MagicMock()
        context.chat_data = {}

        with patch("handlers.base.israel_today") as mock_today, \
             patch("handlers.base.detect_mode_change", return_value=None), \
             patch("handlers.base.safe_react", new_callable=AsyncMock), \
             patch("handlers.base.is_edit_request", return_value=False):
            import datetime
            mock_today.return_value = datetime.date(2026, 5, 5)

            await ExpenseHandlers.handle_message(handler, update, context)

        # Should NOT have appended anything
        handler.sheets.append_expense.assert_not_called()
        message.reply_text.assert_not_called()


# ---------- Confirm-before-categorize tests ----------

class TestConfirmCategorization:
    """New flow: expenses are always recorded as "אחר"; GPT's category is only a
    suggestion the user confirms in a following message."""

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
        handler._categories = ["אוכל", "תחבורה", "אחר"]
        handler._directives = []
        handler._popular_categories = []
        handler.currency_list = ["שקל"]
        handler.default_currency = "שקל"
        handler.currency_lookup = {}
        handler.sheets = MagicMock()
        handler.sheets.append_expense.return_value = 5
        handler.categorizer = MagicMock()
        handler.mongo = MagicMock()
        return handler

    @pytest.mark.asyncio
    async def test_real_suggestion_recorded_as_other_and_confirmation_sent(self):
        from handlers.base import ExpenseHandlers
        from categorizer import ParseResult, ParsedExpense

        handler = self._make_handler()
        handler.categorizer.parse_message.return_value = ParseResult(
            type="expenses",
            expenses=[ParsedExpense(amount=30, description="קפה", category="אוכל",
                                    currency="שקל", date=None)],
        )
        handler._handle_reply_edit = AsyncMock(return_value=False)
        handler._handle_pending_question = AsyncMock(return_value=False)
        handler._handle_pending_edit = AsyncMock(return_value=False)
        handler._get_user_currency = MagicMock(return_value="שקל")
        handler._try_fallback_expense = ExpenseHandlers._try_fallback_expense
        handler._record_and_confirm = ExpenseHandlers._record_and_confirm.__get__(handler, ExpenseHandlers)

        ack_msg = MagicMock(); ack_msg.message_id = 100
        conf_msg = MagicMock(); conf_msg.message_id = 999

        message = MagicMock()
        message.text = "קפה 30"
        message.chat_id = 123
        message.from_user.id = 1
        message.set_reaction = AsyncMock()
        message.reply_text = AsyncMock(side_effect=[ack_msg, conf_msg])

        update = MagicMock()
        update.effective_message = message

        context = MagicMock()
        context.chat_data = {}

        with patch("handlers.base.israel_today") as mock_today, \
             patch("handlers.base.detect_mode_change", return_value=None), \
             patch("handlers.base.safe_react", new_callable=AsyncMock), \
             patch("handlers.base.is_edit_request", return_value=False):
            import datetime
            mock_today.return_value = datetime.date(2026, 5, 5)

            await ExpenseHandlers.handle_message(handler, update, context)

        # Recorded as "אחר" even though GPT suggested "אוכל"
        handler.sheets.update_category.assert_called_once()
        assert handler.sheets.update_category.call_args[0][1] == "אחר"
        # Two messages: acknowledgment + following confirmation
        assert message.reply_text.call_count == 2
        # Confirmation state stored keyed by the confirmation message id
        assert context.chat_data.get("suggest_999") == "אוכל"
        assert context.chat_data.get("catflow_999") is True
        assert context.chat_data.get("editing_999", {}).get("row_number") == 5


# ---------- GPT prompt content tests ----------

class TestGPTPromptContent:
    """Verify the GPT system prompt contains strong brackets and prefer-expenses rules."""

    @pytest.fixture(autouse=True)
    def _stub_imports(self):
        stubs = {}
        for mod_name in [
            "telegram", "telegram.ext", "telegram.constants",
            "pymongo",
            "bot", "storage",
            "handlers", "handlers.base", "handlers.edit_handlers",
            "handlers.menu_handlers", "handlers.insights_handlers", "handlers.utils",
            "parsing", "keyboards",
        ]:
            if mod_name not in sys.modules:
                stubs[mod_name] = MagicMock()
        with patch.dict(sys.modules, stubs):
            if "categorizer" in sys.modules:
                del sys.modules["categorizer"]
            yield
            if "categorizer" in sys.modules:
                del sys.modules["categorizer"]

    def _capture_system_prompt(self):
        """Call parse_message with a mock OpenAI client and capture the system prompt."""
        with patch("categorizer.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.parsed = None  # Will return unknown
            mock_client.beta.chat.completions.parse.return_value = mock_response
            MockOpenAI.return_value = mock_client

            from categorizer import Categorizer
            cat = Categorizer(api_key="fake")
            cat.parse_message(
                text="test",
                categories=["אוכל", "טיסות"],
                directives=[],
                currencies=["שקל"],
                default_currency="שקל",
                today_str="05/05/2026",
            )

            call_args = mock_client.beta.chat.completions.parse.call_args
            messages = call_args[1]["messages"]
            return messages[0]["content"]

    def test_prompt_has_strong_brackets_rule(self):
        prompt = self._capture_system_prompt()
        # Should contain "כלל קריטי" about brackets
        assert "סוגריים" in prompt
        # Should explicitly say the brackets DETERMINE the category, not just hint
        assert "הוראה מפורשת" in prompt or "חייב להתבסס" in prompt

    def test_prompt_has_prefer_expenses_rule(self):
        prompt = self._capture_system_prompt()
        # Should mention preferring expenses type when a number is present
        assert "אחר" in prompt
        # Should tell GPT to use אחר when unsure but number exists
        assert "העדפ" in prompt or "expenses" in prompt.lower()
