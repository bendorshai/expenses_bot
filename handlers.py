from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date, datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from sheets import SheetsClient
from categorizer import Categorizer
from parsing import parse_date_token, detect_mode_change, parse_expense_line, build_currency_lookup
from keyboards import (
    THUMBS_UP, OK_HAND,
    CALLBACK_PREFIX_EDIT, CALLBACK_PREFIX_EDIT_DESC, CALLBACK_PREFIX_EDIT_AMT,
    CALLBACK_PREFIX_EDIT_DATE, CALLBACK_PREFIX_EDIT_CAT, CALLBACK_PREFIX_EDIT_CUR,
    CALLBACK_PREFIX_CAT, CALLBACK_PREFIX_CUR_SET, CALLBACK_PREFIX_CUR_MENU,
    CALLBACK_PREFIX_UPDATE, CALLBACK_PREFIX_DELETE, CALLBACK_PREFIX_DIRECTIVE,
    CALLBACK_PREFIX_INSIGHTS_SUMMARY, CALLBACK_PREFIX_INSIGHTS_ASK,
    CALLBACK_PREFIX_BACK, CALLBACK_PREFIX_BACK_EDIT, CALLBACK_PREFIX_MAIN_MENU,
    make_edit_button, make_edit_menu_keyboard, make_cancel_keyboard,
    make_categories_keyboard, make_currency_keyboard, make_insights_keyboard,
    make_main_menu_keyboard, base_text,
)

logger = logging.getLogger(__name__)

MAX_TG_LENGTH = 4096
PENDING_STATE_TTL = 300  # 5 minutes


async def _send_long_text(message, text: str, reply_markup=None) -> None:
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

        if await self._handle_pending_question(message, context):
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
            await self._answer_freetext_question(message)
            return

        await message.set_reaction(THUMBS_UP)

        user_mode_currency = self._get_user_currency(context, user_id, self.default_currency)
        categories = self._categories
        directives = self._directives

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

        self._schedule_welcome(context)

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
                feedback = message.text.strip()
                directive = self.categorizer.craft_directive(feedback)
                if directive:
                    self.sheets.append_directive(directive)
                    self._directives.append(directive)
                    status = f"✓ הנחיה נשמרה: {directive}"
                else:
                    status = "❌ לא הצלחתי ליצור הנחיה"
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
            "timestamp": time.time(),
        }
        base = base_text(query.message.text or "")
        await query.edit_message_text(
            f"{base}\n\nהקלד תיאור חדש:", reply_markup=make_cancel_keyboard(row_number),
        )

    async def handle_edit_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
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
        await query.answer()
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
        await query.answer()
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
        await query.answer()
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_EDIT_CUR))
        keyboard = make_currency_keyboard(row_number, self.currency_list)
        base = base_text(query.message.text or "")
        await query.edit_message_text(f"{base}\n\nבחר מטבע:", reply_markup=keyboard)

    async def handle_directive(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
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
        await query.answer()

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
    # Insights
    # ------------------------------------------------------------------

    @staticmethod
    def _build_expenses_csv(expenses: list[dict[str, str]]) -> str:
        lines = ["תאריך,תיאור,סכום,סיווג,מטבע"]
        for e in expenses:
            d = e.get("תאריך", "")
            desc = e.get("תיאור", "")
            amt = e.get("חובה", "0")
            cat = e.get("סיווג", "")
            cur = e.get("מטבע", "")
            lines.append(f"{d},{desc},{amt},{cat},{cur}")
        return "\n".join(lines)

    @staticmethod
    def _build_monthly_summary(expenses: list[dict[str, str]]) -> str:
        HEBREW_MONTHS = {
            1: "ינואר", 2: "פברואר", 3: "מרץ", 4: "אפריל",
            5: "מאי", 6: "יוני", 7: "יולי", 8: "אוגוסט",
            9: "ספטמבר", 10: "אוקטובר", 11: "נובמבר", 12: "דצמבר",
        }
        months: dict[str, dict[str, dict[str, float]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(float))
        )
        month_totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

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
                sort_key = d.strftime("%Y-%m")
            except ValueError:
                continue
            months[sort_key][currency][category] += amount
            month_totals[sort_key][currency] += amount

        if not months:
            return "אין נתונים להצגה."

        lines: list[str] = []
        for sort_key in sorted(months.keys()):
            year, mon = sort_key.split("-")
            month_name = HEBREW_MONTHS.get(int(mon), mon)
            lines.append(f"📅  {month_name} {year}")
            lines.append("─" * 22)
            for currency in sorted(months[sort_key]):
                total = month_totals[sort_key][currency]
                lines.append(f"  💰 {currency}: {total:,.1f}")
                cats = months[sort_key][currency]
                for cat, amt in sorted(cats.items(), key=lambda x: -x[1]):
                    bar_len = int(amt / total * 10) if total else 0
                    bar = "▓" * bar_len + "░" * (10 - bar_len)
                    lines.append(f"      {bar} {cat}: {amt:,.1f}")
            lines.append("")

        return "\n".join(lines)

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
            summary = self._build_monthly_summary(expenses)
            header = f"📊 סיכום חודשי — {len(expenses)} הוצאות\n\n"
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
            csv_data = self._build_expenses_csv(expenses)
            answer = self.categorizer.analyze_expenses(question, csv_data)
            reply = answer if answer else "❌ לא הצלחתי לנתח את הנתונים"
        except Exception:
            logger.exception("Failed to analyze freetext question")
            reply = "❌ שגיאה בניתוח הנתונים"
        keyboard = make_insights_keyboard()
        try:
            await _send_long_text(message, f"🔍 {question}\n\n{reply}", reply_markup=keyboard)
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
            csv_data = self._build_expenses_csv(expenses)
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
                await _send_long_text(message, full_text, reply_markup=keyboard)
        except Exception:
            logger.exception("Could not send pending question reply")
            try:
                await _send_long_text(message, full_text, reply_markup=keyboard)
            except Exception:
                pass

        try:
            await message.set_reaction(OK_HAND)
        except Exception:
            pass
        return True

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

    async def handle_back_to_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to the edit menu from category/currency grids or cancel a pending text input."""
        query = update.callback_query
        await query.answer()
        row_number = int(query.data.removeprefix(CALLBACK_PREFIX_BACK_EDIT))

        context.chat_data.pop("pending_edit", None)

        editing = context.chat_data.get(f"editing_{query.message.message_id}", {})
        description = editing.get("description", "")
        base = editing.get("base_text", base_text(query.message.text or ""))

        keyboard = make_edit_menu_keyboard(row_number)
        await query.edit_message_text(f"{base}\n\nעריכה: {description}", reply_markup=keyboard)

    # ------------------------------------------------------------------
    # Main menu / Welcome
    # ------------------------------------------------------------------

    WELCOME_TEXT = (
        "שלום! 👋\n"
        "להוספת הוצאות, פשוט שלח הודעה, למשל: חלב 15\n"
        "או בחר אחת מהאפשרויות:"
    )

    async def _send_welcome(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send the welcome / main-menu message to the configured chat."""
        keyboard = make_main_menu_keyboard()
        await context.bot.send_message(
            chat_id=self.chat_id, text=self.WELCOME_TEXT, reply_markup=keyboard,
        )

    async def handle_start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message or message.chat_id != self.chat_id:
            return
        keyboard = make_main_menu_keyboard()
        await message.reply_text(self.WELCOME_TEXT, reply_markup=keyboard)

    async def handle_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        action = query.data.removeprefix(CALLBACK_PREFIX_MAIN_MENU)

        context.chat_data.pop("pending_question", None)

        if action == "home":
            keyboard = make_main_menu_keyboard()
            await query.edit_message_text(self.WELCOME_TEXT, reply_markup=keyboard)

        elif action == "currency":
            user_id = query.from_user.id if query.from_user else 0
            current = self._get_user_currency(context, user_id, self.default_currency)
            available = ", ".join(self.currency_list)
            keyboard = make_main_menu_keyboard()
            await query.edit_message_text(
                f"💱 מצב מטבע נוכחי: {current}\n\n"
                f"מטבעות זמינים: {available}\n\n"
                "לשינוי מטבע, שלח: מצב <שם מטבע>",
                reply_markup=keyboard,
            )

        elif action == "directives":
            keyboard = make_main_menu_keyboard()
            if self._directives:
                numbered = "\n".join(f"  {i}. {d}" for i, d in enumerate(self._directives, 1))
                text = f"📋 הנחיות סיווג קיימות:\n\n{numbered}"
            else:
                text = "📋 אין הנחיות סיווג כרגע.\nאפשר להוסיף דרך עריכת הוצאה."
            await query.edit_message_text(text, reply_markup=keyboard)

    # ------------------------------------------------------------------
    # Idle welcome timer
    # ------------------------------------------------------------------

    def _schedule_welcome(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Cancel any pending welcome job and schedule a new one 60s from now."""
        old_job = context.chat_data.get("welcome_job")
        if old_job is not None:
            old_job.schedule_removal()
            context.chat_data.pop("welcome_job", None)

        job_queue = context.application.job_queue
        if job_queue is None:
            return

        job = job_queue.run_once(self._welcome_job_callback, when=60, chat_id=self.chat_id)
        context.chat_data["welcome_job"] = job

    async def _welcome_job_callback(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_data = context.application.chat_data.get(self.chat_id, {})
        chat_data.pop("welcome_job", None)
        await self._send_welcome(context)
