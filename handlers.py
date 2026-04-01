from __future__ import annotations

import logging
from datetime import date

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from sheets import SheetsClient
from categorizer import Categorizer
from parsing import parse_date_token, detect_mode_change, parse_expense_line
from keyboards import (
    THUMBS_UP, OK_HAND,
    CALLBACK_PREFIX_EDIT, CALLBACK_PREFIX_EDIT_DESC, CALLBACK_PREFIX_EDIT_AMT,
    CALLBACK_PREFIX_EDIT_DATE, CALLBACK_PREFIX_EDIT_CAT, CALLBACK_PREFIX_EDIT_CUR,
    CALLBACK_PREFIX_CAT, CALLBACK_PREFIX_CUR_SET, CALLBACK_PREFIX_CUR_MENU,
    CALLBACK_PREFIX_UPDATE, CALLBACK_PREFIX_DELETE, CALLBACK_PREFIX_BACK,
    make_edit_button, make_edit_menu_keyboard,
    make_categories_keyboard, make_currency_keyboard, base_text,
)

logger = logging.getLogger(__name__)


class ExpenseHandlers:
    def __init__(
        self,
        chat_id: int,
        sheets_client: SheetsClient,
        categorizer: Categorizer,
        currency_list: list[str],
        default_currency: str,
        currency_lookup: dict[str, str],
    ):
        self.chat_id = chat_id
        self.sheets = sheets_client
        self.categorizer = categorizer
        self.currency_list = currency_list
        self.default_currency = default_currency
        self.currency_lookup = currency_lookup

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_user_currency(context: ContextTypes.DEFAULT_TYPE, user_id: int, default: str) -> str:
        user_currencies = context.chat_data.setdefault("user_currencies", {})
        return user_currencies.get(user_id, default)

    @staticmethod
    def _set_user_currency(context: ContextTypes.DEFAULT_TYPE, user_id: int, currency: str) -> None:
        user_currencies = context.chat_data.setdefault("user_currencies", {})
        user_currencies[user_id] = currency

    async def _process_single_expense(
        self,
        description: str,
        amount: float,
        currency: str,
        categories: list[str],
        directives: list[str],
        expense_date: date | None = None,
    ) -> tuple[int, str]:
        row_number = self.sheets.append_expense(
            amount=amount, description=description, currency=currency, expense_date=expense_date,
        )
        logger.info("Recorded expense: %s %s [%s] (row %d)", amount, description, currency, row_number)

        category = ""
        try:
            category = self.categorizer.categorize(description, categories, directives)
            if category:
                self.sheets.update_category(row_number, category)
                logger.info("Categorized '%s' -> '%s'", description, category)
        except Exception:
            logger.exception("Failed to categorize expense: %s", description)

        return row_number, category

    # ------------------------------------------------------------------
    # Message handler
    # ------------------------------------------------------------------

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message or not message.text:
            return

        if message.chat_id != self.chat_id:
            return

        user_id = message.from_user.id if message.from_user else 0

        mode_currency = detect_mode_change(message.text, self.currency_lookup)
        if mode_currency:
            self._set_user_currency(context, user_id, mode_currency)
            await message.reply_text(f"מצב מטבע עודכן: {mode_currency}")
            await message.set_reaction(OK_HAND)
            return

        if await self._handle_pending_edit(message, context):
            return

        lines = [line.strip() for line in message.text.strip().splitlines() if line.strip()]
        expenses = []
        for line in lines:
            parsed = parse_expense_line(line, self.currency_lookup)
            if parsed:
                expenses.append(parsed)

        if not expenses:
            return

        await message.set_reaction(THUMBS_UP)

        user_mode_currency = self._get_user_currency(context, user_id, self.default_currency)
        categories = self.sheets.get_categories()
        directives = self.sheets.get_directives()

        results = []
        all_buttons: list[list] = []
        for amount, description, inline_currency, expense_date in expenses:
            currency = inline_currency or user_mode_currency
            try:
                row_number, category = await self._process_single_expense(
                    description, amount, currency, categories, directives,
                    expense_date=expense_date,
                )
                cat_display = category if category else "לא זוהה"
                date_display = expense_date.strftime("%d/%m/%Y") if expense_date else None
                results.append((row_number, description, cat_display, currency, date_display))
                all_buttons.append(make_edit_button(row_number, description))
            except Exception:
                logger.exception("Failed to record expense: %s", description)

        if not results:
            return

        reply_lines = []
        for _, description, cat_display, currency, date_display in results:
            line = f"{description}: {cat_display} [{currency}]"
            if date_display:
                line += f" ({date_display})"
            reply_lines.append(line)

        keyboard = InlineKeyboardMarkup(all_buttons)
        reply_msg = await message.reply_text("\n".join(reply_lines), reply_markup=keyboard)
        context.chat_data[f"buttons_{reply_msg.message_id}"] = all_buttons
        await message.set_reaction(OK_HAND)

    async def _handle_pending_edit(self, message, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Process a pending inline-edit if one exists. Returns True if handled."""
        pending = context.chat_data.get("pending_edit")
        if not pending:
            return False

        del context.chat_data["pending_edit"]
        row_number = pending["row_number"]
        edit_type = pending["type"]
        bot_message_id = pending["bot_message_id"]
        editing = context.chat_data.get(f"editing_{bot_message_id}", {})

        status = ""
        try:
            if edit_type == "description":
                new_val = message.text.strip()
                self.sheets.update_description(row_number, new_val)
                editing["description"] = new_val
                context.chat_data[f"editing_{bot_message_id}"] = editing
                status = f"✓ תיאור עודכן: {new_val}"
            elif edit_type == "amount":
                new_val = float(message.text.strip())
                self.sheets.update_amount(row_number, new_val)
                status = f"✓ סכום עודכן: {new_val}"
            elif edit_type == "date":
                parsed = parse_date_token(message.text.strip())
                if parsed:
                    self.sheets.update_date(row_number, parsed)
                    status = f"✓ תאריך עודכן: {parsed.strftime('%d/%m/%Y')}"
                else:
                    status = "❌ תאריך לא תקין"
        except ValueError:
            status = "❌ ערך לא תקין"
        except Exception:
            logger.exception("Failed to process edit")
            status = "❌ שגיאה בעדכון"

        description = editing.get("description", "")
        base = editing.get("base_text", "")
        keyboard = make_edit_menu_keyboard(row_number)
        text = base
        if status:
            text += f"\n\n{status}"
        text += f"\n\nעריכה: {description}"

        try:
            await context.bot.edit_message_text(
                chat_id=message.chat_id,
                message_id=bot_message_id,
                text=text,
                reply_markup=keyboard,
            )
        except Exception:
            logger.debug("Could not edit bot message after pending edit")
        try:
            await message.set_reaction(OK_HAND)
        except Exception:
            pass
        return True

    # ------------------------------------------------------------------
    # Edit menu flow
    # ------------------------------------------------------------------

    async def handle_edit_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
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
        await query.answer()
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_EDIT_DESC))
        context.chat_data["pending_edit"] = {
            "type": "description",
            "row_number": row_number,
            "bot_message_id": query.message.message_id,
        }
        base = base_text(query.message.text or "")
        await query.edit_message_text(f"{base}\n\nהקלד תיאור חדש:")

    async def handle_edit_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_EDIT_AMT))
        context.chat_data["pending_edit"] = {
            "type": "amount",
            "row_number": row_number,
            "bot_message_id": query.message.message_id,
        }
        base = base_text(query.message.text or "")
        await query.edit_message_text(f"{base}\n\nהקלד סכום חדש:")

    async def handle_edit_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_EDIT_DATE))
        context.chat_data["pending_edit"] = {
            "type": "date",
            "row_number": row_number,
            "bot_message_id": query.message.message_id,
        }
        base = base_text(query.message.text or "")
        await query.edit_message_text(f"{base}\n\nהקלד תאריך (dd/mm/yyyy, אתמול, שלשום):")

    async def handle_edit_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_EDIT_CAT))
        categories = self.sheets.get_categories()
        if not categories:
            await query.edit_message_text("אין קטגוריות מוגדרות בגיליון")
            return
        keyboard = make_categories_keyboard(row_number, categories)
        base = base_text(query.message.text or "")
        await query.edit_message_text(f"{base}\n\nבחר קטגוריה:", reply_markup=keyboard)

    async def handle_edit_currency(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_EDIT_CUR))
        keyboard = make_currency_keyboard(row_number, self.currency_list)
        base = base_text(query.message.text or "")
        await query.edit_message_text(f"{base}\n\nבחר מטבע:", reply_markup=keyboard)

    # ------------------------------------------------------------------
    # Selection callbacks (category / currency)
    # ------------------------------------------------------------------

    async def handle_update_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_UPDATE))
        categories = self.sheets.get_categories()
        if not categories:
            await query.edit_message_text("אין קטגוריות מוגדרות בגיליון")
            return

        keyboard = make_categories_keyboard(row_number, categories)
        current_text = query.message.text or ""
        await query.edit_message_text(f"{current_text}\n\nבחר קטגוריה:", reply_markup=keyboard)

    async def handle_category_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        payload = query.data.removeprefix(CALLBACK_PREFIX_CAT)
        row_str, category = payload.split(":", 1)
        row_number = int(row_str)

        try:
            self.sheets.update_category(row_number, category)
            logger.info("Category update: row %d -> '%s'", row_number, category)

            editing = context.chat_data.get(f"editing_{query.message.message_id}", {})
            description = editing.get("description", "")
            base = editing.get("base_text", base_text(query.message.text or ""))

            keyboard = make_edit_menu_keyboard(row_number)
            await query.edit_message_text(
                f"{base}\n\n✓ סיווג עודכן: {category}\n\nעריכה: {description}",
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception("Failed to update category for row %d", row_number)
            await query.edit_message_text("שגיאה בעדכון הסיווג")

    async def handle_currency_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_CUR_MENU))
        keyboard = make_currency_keyboard(row_number, self.currency_list)
        current_text = query.message.text or ""
        await query.edit_message_text(f"{current_text}\n\nבחר מטבע:", reply_markup=keyboard)

    async def handle_currency_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        payload = query.data.removeprefix(CALLBACK_PREFIX_CUR_SET)
        row_str, currency = payload.split(":", 1)
        row_number = int(row_str)

        try:
            self.sheets.update_currency(row_number, currency)
            logger.info("Currency update: row %d -> '%s'", row_number, currency)

            editing = context.chat_data.get(f"editing_{query.message.message_id}", {})
            description = editing.get("description", "")
            base = editing.get("base_text", base_text(query.message.text or ""))

            keyboard = make_edit_menu_keyboard(row_number)
            await query.edit_message_text(
                f"{base}\n\n✓ מטבע עודכן: {currency}\n\nעריכה: {description}",
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception("Failed to update currency for row %d", row_number)
            await query.edit_message_text("שגיאה בעדכון המטבע")

    # ------------------------------------------------------------------
    # Delete / Back
    # ------------------------------------------------------------------

    async def handle_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
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
        await query.answer()
        stored_buttons = context.chat_data.get(f"buttons_{query.message.message_id}", [])
        keyboard = InlineKeyboardMarkup(stored_buttons) if stored_buttons else None
        base = base_text(query.message.text or "")
        await query.edit_message_text(base, reply_markup=keyboard)
