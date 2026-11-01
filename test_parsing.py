"""TDD tests for parsing helpers.

extract_exact_category implements deterministic, software-only categorization:
only a bracketed (X) that EXACTLY matches a defined category assigns that category.
"""

from __future__ import annotations

from parsing import extract_exact_category

CATEGORIES = ["אוכל בחוץ", "קניות", "תחבורה", "אחר"]


class TestExtractExactCategory:
    def test_exact_match_returns_canonical(self):
        assert extract_exact_category("שווארמה 55 (אוכל בחוץ)", CATEGORIES) == "אוכל בחוץ"

    def test_whitespace_inside_parens_is_trimmed(self):
        assert extract_exact_category("שווארמה 55 (  אוכל בחוץ )", CATEGORIES) == "אוכל בחוץ"

    def test_non_exact_match_returns_none(self):
        assert extract_exact_category("קפה 12 (טעים)", CATEGORIES) is None

    def test_partial_match_returns_none(self):
        # "אוכל" alone is not a category (only "אוכל בחוץ" is).
        assert extract_exact_category("קפה 12 (אוכל)", CATEGORIES) is None

    def test_no_parentheses_returns_none(self):
        assert extract_exact_category("קפה 12 אוכל בחוץ", CATEGORIES) is None

    def test_first_exact_match_wins_among_many(self):
        assert extract_exact_category("x (לא קטגוריה) (קניות)", CATEGORIES) == "קניות"

    def test_empty_categories_returns_none(self):
        assert extract_exact_category("קפה (קניות)", []) is None

    def test_empty_parens_returns_none(self):
        assert extract_exact_category("קפה ()", CATEGORIES) is None
