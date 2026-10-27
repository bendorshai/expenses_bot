from __future__ import annotations

import logging
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from keyboards import (
    CALLBACK_PREFIX_MAIN_MENU,
    make_main_menu_keyboard, make_currency_mode_keyboard,
)
from handlers.utils import safe_answer

logger = logging.getLogger(__name__)


class MenuHandlersMixin:
    """Handlers for the main menu, welcome message, and idle timer."""

    WELCOME_TEXT = (
        "שלום! 👋\n"
        "להוספת הוצאות, פשוט שלח הודעה, למשל: חלב 15\n"
        "או בחר אחת מהאפשרויות:\n\n"
        "🆕 עכשיו תומכים במטבעות נוספים! ריאל ברזילאי וקולון קוסטה־ריקני.\n"
        "אפשר לעבור מטבע דרך תפריט 💱 עדכן מצב מטבע."
    )

    async def handle_start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message or message.chat_id != self.chat_id:
            return
        keyboard = make_main_menu_keyboard()
        await message.reply_text(self.WELCOME_TEXT, reply_markup=keyboard)

    async def handle_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)
        action = query.data.removeprefix(CALLBACK_PREFIX_MAIN_MENU)

        context.chat_data.pop("pending_question", None)
        context.chat_data.pop("pending_edit", None)
        context.chat_data.pop("pending_income", None)

        if action == "home":
            keyboard = make_main_menu_keyboard()
            await query.edit_message_text(self.WELCOME_TEXT, reply_markup=keyboard)

        elif action == "income":
            context.chat_data["pending_income"] = {
                "step": "description",
                "bot_message_id": query.message.message_id,
                "timestamp": time.time(),
            }
            cancel_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("חזור לתפריט", callback_data=f"{CALLBACK_PREFIX_MAIN_MENU}home")],
            ])
            await query.edit_message_text(
                "➕ הוספת הכנסה\n\n✏️ מה לרשום בתיאור?",
                reply_markup=cancel_keyboard,
            )

        elif action == "currency":
            user_id = query.from_user.id if query.from_user else 0
            current = self._get_user_currency(context, user_id, self.default_currency)
            keyboard = make_currency_mode_keyboard(self.currency_list, current)
            await query.edit_message_text(
                f"💱 מצב מטבע נוכחי: {current}\n\nבחר מטבע:",
                reply_markup=keyboard,
            )

        elif action.startswith("curset_"):
            currency = action.removeprefix("curset_")
            user_id = query.from_user.id if query.from_user else 0
            saved = self._set_user_currency(context, user_id, currency)
            db_status = "✅ נשמר במסד הנתונים" if saved else "⚠️ לא הצלחתי לשמור במסד הנתונים"
            keyboard = make_main_menu_keyboard()
            await query.edit_message_text(
                f"✓ מצב מטבע עודכן: {currency}\n{db_status}",
                reply_markup=keyboard,
            )

        elif action == "directives":
            if self._directives:
                numbered = "\n".join(f"  {i}. {d}" for i, d in enumerate(self._directives, 1))
                text = f"📋 הנחיות סיווג קיימות:\n\n{numbered}"
            else:
                text = "📋 אין הנחיות סיווג כרגע."
            add_btn = InlineKeyboardButton("✏️ הוסף הנחיה", callback_data=f"{CALLBACK_PREFIX_MAIN_MENU}add_directive")
            back_btn = InlineKeyboardButton("חזור", callback_data=f"{CALLBACK_PREFIX_MAIN_MENU}home")
            keyboard = InlineKeyboardMarkup([[add_btn], [back_btn]])
            await query.edit_message_text(text, reply_markup=keyboard)

        elif action == "add_directive":
            context.chat_data["pending_edit"] = {
                "type": "directive",
                "row_number": 0,
                "bot_message_id": query.message.message_id,
                "from_menu": True,
                "timestamp": time.time(),
            }
            directives_display = ""
            if self._directives:
                numbered = "\n".join(f"  {i}. {d}" for i, d in enumerate(self._directives, 1))
                directives_display = f"\n\n📋 הנחיות קיימות:\n{numbered}\n"
            cancel_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("ביטול", callback_data=f"{CALLBACK_PREFIX_MAIN_MENU}directives")],
            ])
            await query.edit_message_text(
                f"הנחיות סיווג{directives_display}\n✏️ שלח הנחיה חדשה לסיווג (בטקסט חופשי):",
                reply_markup=cancel_keyboard,
            )
