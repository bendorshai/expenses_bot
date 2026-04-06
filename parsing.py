from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pytz

IL_TZ = pytz.timezone("Asia/Jerusalem")

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
