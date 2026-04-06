from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from keyboards import (
    THUMBS_UP, OK_HAND,
    CALLBACK_PREFIX_INSIGHTS_SUMMARY, CALLBACK_PREFIX_INSIGHTS_ASK,
    CALLBACK_PREFIX_MAIN_MENU,
    make_insights_keyboard, make_main_menu_keyboard,
)
from parsing import israel_today
from handlers.utils import MAX_TG_LENGTH, PENDING_STATE_TTL, send_long_text

logger = logging.getLogger(__name__)

HEBREW_MONTHS = {
    1: "ינואר", 2: "פברואר", 3: "מרץ", 4: "אפריל",
    5: "מאי", 6: "יוני", 7: "יולי", 8: "אוגוסט",
    9: "ספטמבר", 10: "אוקטובר", 11: "נובמבר", 12: "דצמבר",
}


def build_expenses_csv(expenses: list[dict[str, str]]) -> str:
    lines = ["תאריך,תיאור,סכום,סיווג,מטבע"]
    for e in expenses:
        d = e.get("תאריך", "")
        desc = e.get("תיאור", "")
        amt = e.get("חובה", "0")
        cat = e.get("סיווג", "")
        cur = e.get("מטבע", "")
        lines.append(f"{d},{desc},{amt},{cat},{cur}")
    return "\n".join(lines)


def build_monthly_summary(expenses: list[dict[str, str]]) -> str:
    """Build a summary for the current month only."""
    today = israel_today()
    current_key = today.strftime("%Y-%m")

    by_currency: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    totals: dict[str, float] = defaultdict(float)

    for exp in expenses:
        try:
            amount = float(exp.get("חובה", "0") or "0")
        except ValueError:
            continue
        if amount == 0:
            continue
        date_str = exp.get("תאריך", "")
        category = exp.get("סיווג", "") or "ללא סיווג"
        currency = exp.get("מטבע", "") or "שקל"
        try:
            d = datetime.strptime(date_str, "%d/%m/%Y")
            if d.strftime("%Y-%m") != current_key:
                continue
        except ValueError:
            continue
        by_currency[currency][category] += amount
        totals[currency] += amount

    if not by_currency:
        month_name = HEBREW_MONTHS.get(today.month, str(today.month))
        return f"אין נתונים עבור {month_name} {today.year}."

    month_name = HEBREW_MONTHS.get(today.month, str(today.month))
    lines: list[str] = [f"📅  {month_name} {today.year}", "─" * 22]

    for currency in sorted(by_currency):
        total = totals[currency]
        lines.append(f"  💰 {currency}: {total:,.1f}")
        cats = by_currency[currency]
        for cat, amt in sorted(cats.items(), key=lambda x: -x[1]):
            bar_len = int(amt / total * 10) if total else 0
            bar = "▓" * bar_len + "░" * (10 - bar_len)
            lines.append(f"      {bar} {cat}: {amt:,.1f}")

    return "\n".join(lines)


class InsightsHandlersMixin:
    """Handlers for insights: monthly summary and freetext questions."""

    async def handle_insights_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message or message.chat_id != self.chat_id:
            return
        keyboard = make_insights_keyboard()
        await message.reply_text("📊 תובנות על ההוצאות", reply_markup=keyboard)

    async def handle_insights_summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer("טוען נתונים...")
        try:
            expenses = self.sheets.get_all_expenses()
            summary = build_monthly_summary(expenses)
            today = israel_today()
            month_name = HEBREW_MONTHS.get(today.month, str(today.month))
            header = f"📊 סיכום {month_name} {today.year}\n\n"
            text = header + summary

            keyboard = make_insights_keyboard()
            if len(text) > MAX_TG_LENGTH:
                await query.edit_message_text(text[:MAX_TG_LENGTH - 6] + "\n…", reply_markup=keyboard)
            else:
                await query.edit_message_text(text, reply_markup=keyboard)
        except Exception:
            logger.exception("Failed to build monthly summary")
            await query.edit_message_text("❌ שגיאה בטעינת הנתונים")

    async def handle_insights_ask(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        context.chat_data["pending_question"] = {
            "bot_message_id": query.message.message_id,
            "timestamp": time.time(),
        }
        cancel_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("חזור לתפריט", callback_data=f"{CALLBACK_PREFIX_MAIN_MENU}home")],
        ])
        await query.edit_message_text(
            "🔍 שאל שאלה על ההוצאות\n\n"
            "שלח שאלה בטקסט חופשי, למשל:\n"
            "• כמה הוצאתי על אוכל בחוץ בפברואר?\n"
            "• מה הקטגוריה הכי יקרה בחודש האחרון?\n"
            "• כמה פעמים קניתי קפה השבוע?",
            reply_markup=cancel_keyboard,
        )

    async def _answer_freetext_question(self, message) -> None:
        question = message.text.strip()
        logger.info("Freetext question: %s", question)
        try:
            await message.set_reaction(THUMBS_UP)
        except Exception:
            logger.debug("Could not set thumbs-up reaction")
        try:
            expenses = self.sheets.get_all_expenses()
            csv_data = build_expenses_csv(expenses)
            answer = self.categorizer.analyze_expenses(question, csv_data)
            reply = answer if answer else "❌ לא הצלחתי לנתח את הנתונים"
        except Exception:
            logger.exception("Failed to analyze freetext question")
            reply = "❌ שגיאה בניתוח הנתונים"
        keyboard = make_insights_keyboard()
        try:
            await send_long_text(message, f"🔍 {question}\n\n{reply}", reply_markup=keyboard)
        except Exception:
            logger.exception("Failed to send freetext reply")
            try:
                await message.reply_text("❌ שגיאה בשליחת התשובה", reply_markup=keyboard)
            except Exception:
                pass
        try:
            await message.set_reaction(OK_HAND)
        except Exception:
            logger.debug("Could not set ok-hand reaction")

    async def _handle_pending_question(self, message, context: ContextTypes.DEFAULT_TYPE) -> bool:
        pending = context.chat_data.get("pending_question")
        if not pending:
            return False

        if time.time() - pending.get("timestamp", 0) > PENDING_STATE_TTL:
            del context.chat_data["pending_question"]
            return False

        del context.chat_data["pending_question"]
        bot_message_id = pending["bot_message_id"]
        question = message.text.strip()

        await message.set_reaction(THUMBS_UP)

        try:
            expenses = self.sheets.get_all_expenses()
            csv_data = build_expenses_csv(expenses)
            answer = self.categorizer.analyze_expenses(question, csv_data)
            reply = answer if answer else "❌ לא הצלחתי לנתח את הנתונים"
        except Exception:
            logger.exception("Failed to analyze expenses")
            reply = "❌ שגיאה בניתוח הנתונים"

        keyboard = make_insights_keyboard()
        full_text = f"🔍 {question}\n\n{reply}"
        try:
            if len(full_text) <= MAX_TG_LENGTH:
                await context.bot.edit_message_text(
                    chat_id=message.chat_id,
                    message_id=bot_message_id,
                    text=full_text,
                    reply_markup=keyboard,
                )
            else:
                await context.bot.edit_message_text(
                    chat_id=message.chat_id,
                    message_id=bot_message_id,
                    text="🔍 תשובה ארוכה — נשלחת בהודעה נפרדת",
                )
                await send_long_text(message, full_text, reply_markup=keyboard)
        except Exception:
            logger.exception("Could not send pending question reply")
            try:
                await send_long_text(message, full_text, reply_markup=keyboard)
            except Exception:
                pass

        try:
            await message.set_reaction(OK_HAND)
        except Exception:
            pass
        return True
