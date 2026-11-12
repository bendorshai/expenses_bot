from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MAX_TG_LENGTH = 4096
PENDING_STATE_TTL = 300  # 5 minutes

# Hebrew field labels for edit notices, keyed by the internal edit type.
EDIT_FIELD_LABELS = {
    "amount": "סכום",
    "date": "תאריך",
    "description": "תיאור",
    "category": "סיווג",
    "currency": "מטבע",
    "currency_mode": "מצב מטבע",
}


def _fmt_value(value) -> str:
    """Render an old/new value for a notice, using an em dash for empty/None."""
    if value is None:
        return "—"
    text = str(value).strip()
    return text if text else "—"


def format_edit_notice(label_he: str, old, new) -> str:
    """A standalone 'from → to' edit notice, e.g. ✏️ סכום שונה: מ-«10» ל-«20»."""
    return f"✏️ {label_he} שונה: מ-«{_fmt_value(old)}» ל-«{_fmt_value(new)}»"


def format_delete_notice(description, amount=None, currency: str = "") -> str:
    """A standalone deletion notice, e.g. 🗑️ נמחק: חלב — 15 שקל."""
    desc = _fmt_value(description) if description else "רשומה"
    amt = f" — {_fmt_value(amount)}" if amount not in (None, "") else ""
    cur = f" {currency}" if amt and currency else ""
    return f"🗑️ נמחק: {desc}{amt}{cur}"


async def safe_answer(query, text: str = "") -> None:
    """Acknowledge a callback query, silently ignoring failures."""
    try:
        await query.answer(text)
    except Exception:
        logger.debug("Could not answer callback query")


async def safe_react(message, emoji: str) -> None:
    """Set a reaction on a message, silently ignoring failures."""
    try:
        await message.set_reaction(emoji)
    except Exception:
        logger.debug("Could not set reaction %s", emoji)


async def send_long_text(message, text: str, reply_markup=None) -> None:
    """Send text that may exceed Telegram's 4096-char limit, splitting into chunks."""
    if len(text) <= MAX_TG_LENGTH:
        await message.reply_text(text, reply_markup=reply_markup)
        return
    while text:
        if len(text) <= MAX_TG_LENGTH:
            await message.reply_text(text, reply_markup=reply_markup)
            break
        split_at = text.rfind("\n", 0, MAX_TG_LENGTH)
        if split_at <= 0:
            split_at = MAX_TG_LENGTH
        await message.reply_text(text[:split_at])
        text = text[split_at:].lstrip("\n")
