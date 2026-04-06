from __future__ import annotations

MAX_TG_LENGTH = 4096
PENDING_STATE_TTL = 300  # 5 minutes


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
