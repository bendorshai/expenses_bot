from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MAX_TG_LENGTH = 4096
PENDING_STATE_TTL = 300  # 5 minutes


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
