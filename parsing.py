from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pytz

IL_TZ = pytz.timezone("Asia/Jerusalem")

NUM = r"\d+(?:\.\d+)?"

DATE_KEYWORDS: dict[str, int] = {
    "אתמול": 1,
    "שלשום": 2,
}

DATE_NUMERIC_RE = re.compile(
    r"(\d{1,2})[./\-](\d{1,2})(?:[./\-](\d{2,4}))?$"
)

CURRENCY_ALIASES = {
    "שקלים": "שקל",
    "ש״ח": "שקל",
    "שח": "שקל",
    "שקלי": "שקל",
    "אירו": "יורו",
    "euro": "יורו",
    "eur": "יורו",
    "דולרים": "דולר",
    "dollar": "דולר",
    "usd": "דולר",
    "$": "דולר",
    "€": "יורו",
    "₪": "שקל",
}

MODE_CHANGE_PATTERNS = [
    re.compile(r"(?:עבור|עברו|תעבור)\s+(?:ל)?מצב\s+(.+)", re.IGNORECASE),
    re.compile(r"מצב\s+(.+?)(?:\s+עכשיו)?$", re.IGNORECASE),
]

EDIT_TRIGGER_WORDS = {
    "לערוך", "עריכה", "ערוך", "תערוך",
    "לתקן", "תיקון", "תקן", "תתקן", "לתקן",
    "שנה", "לשנות", "שינוי", "תשנה",
    "עדכן", "לעדכן", "עדכון", "תעדכן",
    "fix", "edit", "change", "update",
}


def is_edit_request(text: str) -> bool:
    """Return True if *text* looks like a request to edit an expense."""
    return text.strip().lower() in {w.lower() for w in EDIT_TRIGGER_WORDS}


def israel_today() -> date:
    return datetime.now(IL_TZ).date()


def parse_date_token(token: str) -> date | None:
    """Parse a single token as a date keyword or numeric date. Returns date or None."""
    token = token.strip()

    days_back = DATE_KEYWORDS.get(token)
    if days_back is not None:
        return israel_today() - timedelta(days=days_back)

    m = DATE_NUMERIC_RE.match(token)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        year_str = m.group(3)
        if year_str:
            year = int(year_str)
            if year < 100:
                year += 2000
        else:
            year = israel_today().year
        try:
            return date(year, month, day)
        except ValueError:
            return None

    return None


def build_currency_lookup(currency_list: list[str]) -> dict[str, str]:
    """Build a lookup dict: canonical names map to themselves, plus all aliases."""
    lookup = {}
    for c in currency_list:
        lookup[c] = c
        lookup[c.lower()] = c
    for alias, canonical in CURRENCY_ALIASES.items():
        if canonical in lookup or canonical.lower() in {c.lower() for c in currency_list}:
            target = next((c for c in currency_list if c.lower() == canonical.lower()), canonical)
            lookup[alias] = target
            lookup[alias.lower()] = target
    return lookup


def normalize_currency(text: str, lookup: dict[str, str]) -> str | None:
    key = text.strip()
    return lookup.get(key) or lookup.get(key.lower())


def detect_mode_change(text: str, lookup: dict[str, str]) -> str | None:
    text = text.strip()
    for pattern in MODE_CHANGE_PATTERNS:
        match = pattern.match(text)
        if match:
            raw = match.group(1).strip()
            return normalize_currency(raw, lookup)
    return None


def _strip_date_token(text: str) -> tuple[str, date | None]:
    """Try to extract a date token from the start or end of the text.

    Returns (remaining_text, parsed_date_or_None).
    """
    words = text.split()
    if not words:
        return text, None

    d = parse_date_token(words[0])
    if d is not None:
        return " ".join(words[1:]), d

    d = parse_date_token(words[-1])
    if d is not None:
        return " ".join(words[:-1]), d

    return text, None


def parse_expense_line(text: str, lookup: dict[str, str]) -> tuple[float, str, str | None, date | None] | None:
    """Parse a single expense line. Returns (amount, description, currency_or_None, date_or_None).

    Supported formats (date token optional at start or end):
        [<time>] <amount> [<currency>] <description> [<time>]
        [<time>] <description> <amount> [<currency>] [<time>]
    """
    text = text.strip()
    if not text:
        return None

    text, expense_date = _strip_date_token(text)
    text = text.strip()
    if not text:
        return None

    m = re.match(rf"^({NUM})\s+(.+)$", text)
    if m:
        amount = float(m.group(1))
        rest = m.group(2).strip()
        words = rest.split(maxsplit=1)
        if len(words) >= 2:
            cur = normalize_currency(words[0], lookup)
            if cur:
                return amount, words[1].strip(), cur, expense_date
        return amount, rest, None, expense_date

    m = re.match(rf"^(.+)\s+({NUM})(?:\s+(\S+))?\s*$", text)
    if m:
        description = m.group(1).strip()
        amount = float(m.group(2))
        cur_word = m.group(3)
        cur = normalize_currency(cur_word, lookup) if cur_word else None
        return amount, description, cur, expense_date

    return None
