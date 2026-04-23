from __future__ import annotations

import logging
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from keyboards import (
    OK_HAND,
    CALLBACK_PREFIX_EDIT, CALLBACK_PREFIX_EDIT_DESC, CALLBACK_PREFIX_EDIT_AMT,
    CALLBACK_PREFIX_EDIT_DATE, CALLBACK_PREFIX_EDIT_CAT, CALLBACK_PREFIX_EDIT_CUR,
    CALLBACK_PREFIX_CAT, CALLBACK_PREFIX_CUR_SET, CALLBACK_PREFIX_CUR_MENU,
    CALLBACK_PREFIX_CUR_MODE,
    CALLBACK_PREFIX_UPDATE, CALLBACK_PREFIX_DELETE, CALLBACK_PREFIX_DIRECTIVE,
    CALLBACK_PREFIX_SUGGEST_DIR, CALLBACK_PREFIX_DECLINE_DIR,
    CALLBACK_PREFIX_BACK, CALLBACK_PREFIX_BACK_EDIT,
    make_edit_menu_keyboard, make_cancel_keyboard,
    make_categories_keyboard, make_currency_keyboard, base_text,
)
from handlers.utils import safe_answer

logger = logging.getLogger(__name__)


class EditHandlersMixin:
    """Handlers for the expense edit menu flow."""

    async def handle_edit_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_EDIT))

        description = ""
        if query.message.reply_markup:
            for btn_row in query.message.reply_markup.inline_keyboard:
                for btn in btn_row:
                    if btn.callback_data == query.data:
                        description = btn.text.split(" — ", 1)[-1] if " — " in btn.text else ""
                        break

        base = base_text(query.message.text or "")
        context.chat_data[f"editing_{query.message.message_id}"] = {
            "row_number": row_number,
            "description": description,
            "base_text": base,
        }

        keyboard = make_edit_menu_keyboard(row_number)
        await query.edit_message_text(f"{base}\n\nעריכה: {description}", reply_markup=keyboard)

    async def handle_edit_description(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_EDIT_DESC))
        context.chat_data["pending_edit"] = {
            "type": "description",
            "row_number": row_number,
            "bot_message_id": query.message.message_id,
            "timestamp": time.time(),
        }
        base = base_text(query.message.text or "")
        await query.edit_message_text(
            f"{base}\n\nהקלד תיאור חדש:", reply_markup=make_cancel_keyboard(row_number),
        )

    async def handle_edit_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_EDIT_AMT))
        context.chat_data["pending_edit"] = {
            "type": "amount",
            "row_number": row_number,
            "bot_message_id": query.message.message_id,
            "timestamp": time.time(),
        }
        base = base_text(query.message.text or "")
        await query.edit_message_text(
            f"{base}\n\nהקלד סכום חדש:", reply_markup=make_cancel_keyboard(row_number),
        )

    async def handle_edit_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_EDIT_DATE))
        context.chat_data["pending_edit"] = {
            "type": "date",
            "row_number": row_number,
            "bot_message_id": query.message.message_id,
            "timestamp": time.time(),
        }
        base = base_text(query.message.text or "")
        await query.edit_message_text(
            f"{base}\n\nהקלד תאריך (dd/mm/yyyy, אתמול, שלשום):",
            reply_markup=make_cancel_keyboard(row_number),
        )

    async def handle_edit_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)
        self.refresh_sheets_data()
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_EDIT_CAT))
        categories = self._categories
        if not categories:
            await query.edit_message_text("אין קטגוריות מוגדרות בגיליון")
            return
        keyboard = make_categories_keyboard(row_number, categories)
        base = base_text(query.message.text or "")
        await query.edit_message_text(f"{base}\n\nבחר קטגוריה:", reply_markup=keyboard)

    async def handle_edit_currency(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_EDIT_CUR))
        keyboard = make_currency_keyboard(row_number, self.currency_list)
        base = base_text(query.message.text or "")
        await query.edit_message_text(f"{base}\n\nבחר מטבע:", reply_markup=keyboard)

    async def handle_directive(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_DIRECTIVE))
        context.chat_data["pending_edit"] = {
            "type": "directive",
            "row_number": row_number,
            "bot_message_id": query.message.message_id,
            "timestamp": time.time(),
        }
        base = base_text(query.message.text or "")

        directives_display = ""
        if self._directives:
            numbered = "\n".join(f"  {i}. {d}" for i, d in enumerate(self._directives, 1))
            directives_display = f"\n\n📋 הנחיות קיימות:\n{numbered}\n"

        await query.edit_message_text(
            f"{base}{directives_display}\n✏️ שלח הנחיה חדשה לסיווג (בטקסט חופשי):",
            reply_markup=make_cancel_keyboard(row_number),
        )

    # ------------------------------------------------------------------
    # Selection callbacks (category / currency)
    # ------------------------------------------------------------------

    async def handle_update_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)

        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_UPDATE))
        categories = self._categories
        if not categories:
            await query.edit_message_text("אין קטגוריות מוגדרות בגיליון")
            return

        keyboard = make_categories_keyboard(row_number, categories)
        current_text = query.message.text or ""
        await query.edit_message_text(f"{current_text}\n\nבחר קטגוריה:", reply_markup=keyboard)

    async def handle_category_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)

        payload = query.data.removeprefix(CALLBACK_PREFIX_CAT)
        row_str, category = payload.split(":", 1)
        row_number = int(row_str)

        try:
            self.sheets.update_category(row_number, category)
            logger.info("Category update: row %d -> '%s'", row_number, category)

            editing = context.chat_data.get(f"editing_{query.message.message_id}", {})
            description = editing.get("description", "")
            base = editing.get("base_text", base_text(query.message.text or ""))

            suggested_directive = f"{description} זה {category}"
            context.chat_data[f"suggested_dir_{query.message.message_id}"] = suggested_directive
            context.chat_data[f"suggested_cat_{query.message.message_id}"] = category

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ כן", callback_data=f"{CALLBACK_PREFIX_SUGGEST_DIR}{row_number}"),
                    InlineKeyboardButton("❌ לא", callback_data=f"{CALLBACK_PREFIX_DECLINE_DIR}{row_number}"),
                ],
            ])
            await query.edit_message_text(
                f"{base}\n\n✓ סיווג עודכן: {category}"
                f'\n\n💡 לסווג "{description}" כ"{category}" גם בפעם הבאה?',
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception("Failed to update category for row %d", row_number)
            await query.edit_message_text("שגיאה בעדכון הסיווג")

    async def handle_suggest_directive(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_SUGGEST_DIR))

        directive = context.chat_data.pop(f"suggested_dir_{query.message.message_id}", "")
        editing = context.chat_data.get(f"editing_{query.message.message_id}", {})
        description = editing.get("description", "")
        base = editing.get("base_text", base_text(query.message.text or ""))

        status = ""
        if directive:
            try:
                self.sheets.append_directive(directive)
                self._directives.append(directive)
                status = f'✓ הנחיה נשמרה: "{directive}"'
            except Exception:
                logger.exception("Failed to save suggested directive")
                status = "❌ שגיאה בשמירת ההנחיה"
        else:
            status = "❌ לא נמצאה הנחיה לשמירה"

        keyboard = make_edit_menu_keyboard(row_number)
        await query.edit_message_text(
            f"{base}\n\n{status}\n\nעריכה: {description}",
            reply_markup=keyboard,
        )

    async def handle_decline_directive(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_DECLINE_DIR))

        context.chat_data.pop(f"suggested_dir_{query.message.message_id}", None)
        category = context.chat_data.pop(f"suggested_cat_{query.message.message_id}", "")
        editing = context.chat_data.get(f"editing_{query.message.message_id}", {})
        description = editing.get("description", "")
        base = editing.get("base_text", base_text(query.message.text or ""))

        keyboard = make_edit_menu_keyboard(row_number)
        await query.edit_message_text(
            f"{base}\n\n✓ סיווג עודכן: {category}\n\nעריכה: {description}",
            reply_markup=keyboard,
        )

    async def handle_currency_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)

        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_CUR_MENU))
        keyboard = make_currency_keyboard(row_number, self.currency_list)
        current_text = query.message.text or ""
        await query.edit_message_text(f"{current_text}\n\nבחר מטבע:", reply_markup=keyboard)

    async def handle_currency_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)

        payload = query.data.removeprefix(CALLBACK_PREFIX_CUR_SET)
        row_str, currency = payload.split(":", 1)
        row_number = int(row_str)

        try:
            self.sheets.update_currency(row_number, currency)
            logger.info("Currency update: row %d -> '%s'", row_number, currency)

            editing = context.chat_data.get(f"editing_{query.message.message_id}", {})
            description = editing.get("description", "")
            base = editing.get("base_text", base_text(query.message.text or ""))

            user_id = query.from_user.id if query.from_user else 0
            current_mode = self._get_user_currency(context, user_id, self.default_currency)

            if currency != current_mode:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        f"כן, עבור למצב {currency}",
                        callback_data=f"{CALLBACK_PREFIX_CUR_MODE}{row_number}:{currency}",
                    )],
                    [InlineKeyboardButton("לא, תודה", callback_data=f"{CALLBACK_PREFIX_BACK_EDIT}{row_number}")],
                ])
                await query.edit_message_text(
                    f"{base}\n\n✓ מטבע עודכן: {currency}\n\nלעבור למצב {currency} לכל ההוצאות הבאות?",
                    reply_markup=keyboard,
                )
            else:
                keyboard = make_edit_menu_keyboard(row_number)
                await query.edit_message_text(
                    f"{base}\n\n✓ מטבע עודכן: {currency}\n\nעריכה: {description}",
                    reply_markup=keyboard,
                )
        except Exception:
            logger.exception("Failed to update currency for row %d", row_number)
            await query.edit_message_text("שגיאה בעדכון המטבע")

    async def handle_currency_mode_switch(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)

        payload = query.data.removeprefix(CALLBACK_PREFIX_CUR_MODE)
        row_str, currency = payload.split(":", 1)
        row_number = int(row_str)

        user_id = query.from_user.id if query.from_user else 0
        saved = self._set_user_currency(context, user_id, currency)
        logger.info("Currency mode switched to '%s' for user %d", currency, user_id)

        db_status = "✅ נשמר במסד הנתונים" if saved else "⚠️ לא הצלחתי לשמור במסד הנתונים"
        editing = context.chat_data.get(f"editing_{query.message.message_id}", {})
        description = editing.get("description", "")
        base = editing.get("base_text", base_text(query.message.text or ""))

        keyboard = make_edit_menu_keyboard(row_number)
        await query.edit_message_text(
            f"{base}\n\n✓ מצב מטבע עודכן: {currency}\n{db_status}\n\nעריכה: {description}",
            reply_markup=keyboard,
        )

    # ------------------------------------------------------------------
    # Delete / Back
    # ------------------------------------------------------------------

    async def handle_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_DELETE))
        try:
            self.sheets.delete_row(row_number)
            logger.info("Deleted row %d", row_number)
            base = base_text(query.message.text or "")
            await query.edit_message_text(f"{base}\n\n✓ נמחק")
        except Exception:
            logger.exception("Failed to delete row %d", row_number)
            await query.edit_message_text("שגיאה במחיקה")

    async def handle_back(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await safe_answer(query)
        stored_buttons = context.chat_data.get(f"buttons_{query.message.message_id}", [])
        keyboard = InlineKeyboardMarkup(stored_buttons) if stored_buttons else None
        base = base_text(query.message.text or "")
        await query.edit_message_text(base, reply_markup=keyboard)

    async def handle_back_to_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to the edit menu from category/currency grids or cancel a pending text input."""
        query = update.callback_query
        await safe_answer(query)
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_BACK_EDIT))

        context.chat_data.pop("pending_edit", None)

        editing = context.chat_data.get(f"editing_{query.message.message_id}", {})
        description = editing.get("description", "")
        base = editing.get("base_text", base_text(query.message.text or ""))

        keyboard = make_edit_menu_keyboard(row_number)
        await query.edit_message_text(f"{base}\n\nעריכה: {description}", reply_markup=keyboard)
