"""TDD tests for the standalone edit/delete notice formatters.

Each field edit and each deletion must produce an explicit, separate
'from → to' (or 'deleted') message, so the formatters are pure and tested here.
"""

from __future__ import annotations

from handlers.utils import format_edit_notice, format_delete_notice


class TestFormatEditNotice:
    def test_shows_old_and_new(self):
        assert format_edit_notice("סכום", 10, 20) == "✏️ סכום שונה: מ-«10» ל-«20»"

    def test_strings_are_passed_through(self):
        assert format_edit_notice("מטבע", "שקל", "דולר") == "✏️ מטבע שונה: מ-«שקל» ל-«דולר»"

    def test_empty_old_renders_dash(self):
        assert format_edit_notice("סיווג", "", "אוכל") == "✏️ סיווג שונה: מ-«—» ל-«אוכל»"

    def test_none_old_renders_dash(self):
        assert format_edit_notice("תיאור", None, "חלב") == "✏️ תיאור שונה: מ-«—» ל-«חלב»"

    def test_whitespace_is_trimmed(self):
        assert format_edit_notice("תיאור", "  חלב  ", " גבינה ") == "✏️ תיאור שונה: מ-«חלב» ל-«גבינה»"


class TestFormatDeleteNotice:
    def test_full_record(self):
        assert format_delete_notice("חלב", 15, "שקל") == "🗑️ נמחק: חלב — 15 שקל"

    def test_missing_amount_omits_amount_and_currency(self):
        assert format_delete_notice("חלב", None, "שקל") == "🗑️ נמחק: חלב"

    def test_missing_currency_keeps_amount(self):
        assert format_delete_notice("חלב", 15, "") == "🗑️ נמחק: חלב — 15"

    def test_empty_description_falls_back(self):
        assert format_delete_notice("", 15, "שקל") == "🗑️ נמחק: רשומה — 15 שקל"
