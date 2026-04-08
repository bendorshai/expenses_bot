from __future__ import annotations

import logging
import time
from datetime import datetime

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from sheets import SheetsClient
from categorizer import Categorizer
from storage import MongoStorage
from parsing import parse_date_token, detect_mode_change, build_currency_lookup, is_edit_request, israel_today
from keyboards import (
    THUMBS_UP, OK_HAND,
    CALLBACK_PREFIX_EDIT,
    make_edit_button, make_edit_menu_keyboard, make_main_menu_keyboard, base_text,
)
from handlers.utils import PENDING_STATE_TTL, safe_react
from handlers.edit_handlers import EditHandlersMixin
from handlers.insights_handlers import InsightsHandlersMixin
from handlers.menu_handlers import MenuHandlersMixin

logger = logging.getLogger(__name__)


class ExpenseHandlers(EditHandlersMixin, InsightsHandlersMixin, MenuHandlersMixin):
    def __init__(
        self,
        chat_id: int,
        sheets_client: SheetsClient,
        categorizer: Categorizer,
        currency_list: list[str],
        default_currency: str,
        currency_lookup: dict[str, str],
        mongo_storage: MongoStorage,
    ):
        self.chat_id = chat_id
        self.sheets = sheets_client
        self.categorizer = categorizer
        self.currency_list = currency_list
        self.default_currency = default_currency
        self.currency_lookup = currency_lookup
        self.mongo = mongo_storage
        self._categories: list[str] = sheets_client.get_categories()
        self._directives: list[str] = sheets_client.get_directives()

    def refresh_sheets_data(self) -> None:
        """Re-fetch categories, directives, and currencies from sheets."""
        try:
            self._categories = self.sheets.get_categories()
            self._directives = self.sheets.get_directives()
            new_currencies = self.sheets.get_currencies()
            if new_currencies:
                self.currency_list = new_currencies
                self.default_currency = new_currencies[0]
                self.currency_lookup = build_currency_lookup(new_currencies)
            logger.debug("Refreshed sheets data: %d categories, %d directives, %d currencies",
                         len(self._categories), len(self._directives), len(self.currency_list))
        except Exception:
            logger.exception("Failed to refresh sheets data")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_user_currency(context: ContextTypes.DEFAULT_TYPE, user_id: int, default: str) -> str:
        user_currencies = context.chat_data.setdefault("user_currencies", {})
        return user_currencies.get(user_id, default)

    def _set_user_currency(self, context: ContextTypes.DEFAULT_TYPE, user_id: int, currency: str) -> bool:
        user_currencies = context.chat_data.setdefault("user_currencies", {})
        user_currencies[user_id] = currency
        try:
            self.mongo.set_user_currency(user_id, currency)
            return True
        except Exception:
            logger.exception("Failed to persist currency to MongoDB for user %d", user_id)
            return False

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
            saved = self._set_user_currency(context, user_id, mode_currency)
            db_status = "✅ נשמר במסד הנתונים" if saved else "⚠️ לא הצלחתי לשמור במסד הנתונים"
            await message.reply_text(f"מצב מטבע עודכן: {mode_currency}\n{db_status}")
            await safe_react(message, OK_HAND)
            return

        if await self._handle_reply_edit(message, context):
            return

        if await self._handle_pending_question(message, context):
            return

        if await self._handle_pending_edit(message, context):
            return

        await safe_react(message, THUMBS_UP)

        user_currency = self._get_user_currency(context, user_id, self.default_currency)
        today = israel_today()
        result = self.categorizer.parse_message(
            text=message.text,
            categories=self._categories,
            directives=self._directives,
            currencies=self.currency_list,
            default_currency=user_currency,
            today_str=today.strftime("%d/%m/%Y"),
        )

        if result.type == "query":
            await self._answer_freetext_question(message)
            return

        if result.type == "unknown" or not result.expenses:
            return

        results = []
        all_buttons: list[list] = []
        for expense in result.expenses:
            try:
                expense_date = None
                if expense.date:
                    try:
                        expense_date = datetime.strptime(expense.date, "%d/%m/%Y").date()
                    except ValueError:
                        logger.warning("Invalid date from GPT: %s", expense.date)

                row_number = self.sheets.append_expense(
                    amount=expense.amount,
                    description=expense.description,
                    currency=expense.currency,
                    expense_date=expense_date,
                )
                logger.info("Recorded expense: %s %s [%s] (row %d)",
                            expense.amount, expense.description, expense.currency, row_number)

                if expense.category:
                    self.sheets.update_category(row_number, expense.category)
                    logger.info("Categorized '%s' -> '%s'", expense.description, expense.category)

                cat_display = expense.category if expense.category else "לא זוהה"
                results.append((row_number, expense.description, expense.amount,
                                cat_display, expense.currency, expense.date))
                all_buttons.append(make_edit_button(row_number, expense.description))
            except Exception:
                logger.exception("Failed to record expense: %s", expense.description)

        if not results:
            return

        reply_lines = []
        for _, description, amount, cat_display, currency, date_display in results:
            line = f"{description}: {amount} {currency} — {cat_display}"
            if date_display:
                line += f" ({date_display})"
            reply_lines.append(line)

        keyboard = InlineKeyboardMarkup(all_buttons)
        reply_msg = await message.reply_text("\n".join(reply_lines), reply_markup=keyboard)
        context.chat_data[f"buttons_{reply_msg.message_id}"] = all_buttons
        await safe_react(message, OK_HAND)

        try:
            self._schedule_welcome(context)
        except Exception:
            logger.debug("Could not schedule welcome message")

    async def _handle_reply_edit(self, message, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """If the user replies to a bot expense message with an edit trigger word, open the edit menu."""
        if not message.reply_to_message or not is_edit_request(message.text):
            return False

        replied_msg = message.reply_to_message
        stored_buttons = context.chat_data.get(f"buttons_{replied_msg.message_id}")
        if not stored_buttons:
            return False

        if len(stored_buttons) == 1:
            btn = stored_buttons[0][0]
            row_number = int(btn.callback_data.removeprefix(CALLBACK_PREFIX_EDIT))
            description = btn.text.split(" — ", 1)[-1] if " — " in btn.text else ""
            base = base_text(replied_msg.text or "")
            context.chat_data[f"editing_{replied_msg.message_id}"] = {
                "row_number": row_number,
                "description": description,
                "base_text": base,
            }
            keyboard = make_edit_menu_keyboard(row_number)
            await replied_msg.edit_text(f"{base}\n\nעריכה: {description}", reply_markup=keyboard)
        else:
            keyboard = InlineKeyboardMarkup(stored_buttons)
            await replied_msg.edit_text(
                base_text(replied_msg.text or "") + "\n\nבחר הוצאה לעריכה:",
                reply_markup=keyboard,
            )

        await safe_react(message, OK_HAND)
        return True

    async def _handle_pending_edit(self, message, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Process a pending inline-edit if one exists. Returns True if handled."""
        pending = context.chat_data.get("pending_edit")
        if not pending:
            return False

        if time.time() - pending.get("timestamp", 0) > PENDING_STATE_TTL:
            del context.chat_data["pending_edit"]
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
            elif edit_type == "directive":
                directive = message.text.strip()
                if directive:
                    self.sheets.append_directive(directive)
                    self._directives.append(directive)
                    status = f"✓ הנחיה נשמרה: {directive}"
                else:
                    status = "❌ הנחיה ריקה"
        except ValueError:
            status = "❌ ערך לא תקין"
        except Exception:
            logger.exception("Failed to process edit")
            status = "❌ שגיאה בעדכון"

        if pending.get("from_menu"):
            keyboard = make_main_menu_keyboard()
            text = status or "✓"
        else:
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
