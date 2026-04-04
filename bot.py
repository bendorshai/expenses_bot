from __future__ import annotations

import logging

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    filters,
)

from sheets import SheetsClient
from categorizer import Categorizer
from storage import MongoStorage
from parsing import build_currency_lookup, parse_expense_line
from keyboards import (
    OK_HAND,
    CALLBACK_PREFIX_EDIT, CALLBACK_PREFIX_EDIT_DESC, CALLBACK_PREFIX_EDIT_AMT,
    CALLBACK_PREFIX_EDIT_DATE, CALLBACK_PREFIX_EDIT_CAT, CALLBACK_PREFIX_EDIT_CUR,
    CALLBACK_PREFIX_CAT, CALLBACK_PREFIX_CUR_SET, CALLBACK_PREFIX_CUR_MENU,
    CALLBACK_PREFIX_CUR_MODE,
    CALLBACK_PREFIX_UPDATE, CALLBACK_PREFIX_DELETE, CALLBACK_PREFIX_DIRECTIVE,
    CALLBACK_PREFIX_INSIGHTS_SUMMARY, CALLBACK_PREFIX_INSIGHTS_ASK,
    CALLBACK_PREFIX_BACK, CALLBACK_PREFIX_BACK_EDIT, CALLBACK_PREFIX_MAIN_MENU,
    make_edit_button,
)
from handlers import ExpenseHandlers

logger = logging.getLogger(__name__)


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception while processing update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("❌ שגיאה פנימית. נסה שוב.")
        except Exception:
            pass


async def retroload(
    app: Application,
    chat_id: int,
    sheets_client: SheetsClient,
    categorizer: Categorizer,
    currency_lookup: dict[str, str],
    default_currency: str,
) -> None:
    """Process all pending updates (messages sent while bot was offline)."""
    logger.info("Retroload: fetching pending updates...")

    bot = app.bot
    try:
        await bot.delete_webhook()
        updates = await bot.get_updates(timeout=5)
    except Exception:
        logger.exception("Retroload: failed to fetch updates (another instance may be running)")
        return

    if not updates:
        logger.info("Retroload: no pending updates")
        return

    logger.info("Retroload: found %d pending update(s)", len(updates))

    categories = sheets_client.get_categories()
    directives = sheets_client.get_directives()
    processed = 0

    for update in updates:
        msg = update.message
        if not msg or not msg.text or msg.chat_id != chat_id:
            continue

        lines = [line.strip() for line in msg.text.strip().splitlines() if line.strip()]
        expenses = []
        for line in lines:
            parsed = parse_expense_line(line, currency_lookup)
            if parsed:
                expenses.append(parsed)

        if not expenses:
            logger.info("Retroload: skipping non-expense message: %s", msg.text[:80])
            continue

        results = []
        all_buttons: list[list] = []
        for amount, description, inline_currency, expense_date in expenses:
            currency = inline_currency or default_currency
            try:
                row_number = sheets_client.append_expense(
                    amount=amount, description=description, currency=currency, expense_date=expense_date,
                )
                category = categorizer.categorize(description, categories, directives)
                if category:
                    sheets_client.update_category(row_number, category)
                cat_display = category if category else "לא זוהה"
                date_display = expense_date.strftime("%d/%m/%Y") if expense_date else None
                results.append((row_number, description, cat_display, currency, date_display))
                all_buttons.append(make_edit_button(row_number, description))
                logger.info("Retroload: %s %s [%s] -> row %d, category: %s",
                            amount, description, currency, row_number, category or "N/A")
                processed += 1
            except Exception:
                logger.exception("Retroload: failed to process expense: %s", description)

        if results:
            reply_lines = []
            for _, description, cat_display, currency, date_display in results:
                line = f"{description}: {cat_display} [{currency}]"
                if date_display:
                    line += f" ({date_display})"
                reply_lines.append(line)
            keyboard = InlineKeyboardMarkup(all_buttons)
            try:
                await msg.reply_text("\n".join(reply_lines), reply_markup=keyboard)
            except Exception:
                logger.debug("Retroload: could not reply to message %d", msg.message_id)

        try:
            await msg.set_reaction(OK_HAND)
        except Exception:
            logger.debug("Retroload: could not set reaction on message %d", msg.message_id)

    last_update_id = updates[-1].update_id
    await bot.get_updates(offset=last_update_id + 1, timeout=0)
    logger.info("Retroload: done — processed %d expense(s), acknowledged %d update(s)", processed, len(updates))


def create_bot(
    token: str,
    chat_id: int,
    sheets_client: SheetsClient,
    categorizer: Categorizer,
    currency_list: list[str],
    default_currency: str,
    mongo_storage: MongoStorage,
) -> Application:
    app = Application.builder().token(token).build()
    currency_lookup = build_currency_lookup(currency_list)

    h = ExpenseHandlers(
        chat_id=chat_id,
        sheets_client=sheets_client,
        categorizer=categorizer,
        currency_list=currency_list,
        default_currency=default_currency,
        currency_lookup=currency_lookup,
        mongo_storage=mongo_storage,
    )

    async def _refresh_job(context):
        h.refresh_sheets_data()

    if app.job_queue is not None:
        app.job_queue.run_repeating(_refresh_job, interval=60, first=60)
    else:
        logger.warning("JobQueue not available — install python-telegram-bot[job-queue] for periodic refresh")

    app.add_handler(CommandHandler("start", h.handle_start_command))
    app.add_handler(CommandHandler("insights", h.handle_insights_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, h.handle_message))
    app.add_handler(CallbackQueryHandler(h.handle_edit_button, pattern=f"^{CALLBACK_PREFIX_EDIT}\\d"))
    app.add_handler(CallbackQueryHandler(h.handle_edit_description, pattern=f"^{CALLBACK_PREFIX_EDIT_DESC}"))
    app.add_handler(CallbackQueryHandler(h.handle_edit_amount, pattern=f"^{CALLBACK_PREFIX_EDIT_AMT}"))
    app.add_handler(CallbackQueryHandler(h.handle_edit_date, pattern=f"^{CALLBACK_PREFIX_EDIT_DATE}"))
    app.add_handler(CallbackQueryHandler(h.handle_edit_category, pattern=f"^{CALLBACK_PREFIX_EDIT_CAT}"))
    app.add_handler(CallbackQueryHandler(h.handle_edit_currency, pattern=f"^{CALLBACK_PREFIX_EDIT_CUR}"))
    app.add_handler(CallbackQueryHandler(h.handle_update_button, pattern=f"^{CALLBACK_PREFIX_UPDATE}"))
    app.add_handler(CallbackQueryHandler(h.handle_category_selection, pattern=f"^{CALLBACK_PREFIX_CAT}"))
    app.add_handler(CallbackQueryHandler(h.handle_currency_menu, pattern=f"^{CALLBACK_PREFIX_CUR_MENU}"))
    app.add_handler(CallbackQueryHandler(h.handle_currency_selection, pattern=f"^{CALLBACK_PREFIX_CUR_SET}"))
    app.add_handler(CallbackQueryHandler(h.handle_currency_mode_switch, pattern=f"^{CALLBACK_PREFIX_CUR_MODE}"))
    app.add_handler(CallbackQueryHandler(h.handle_directive, pattern=f"^{CALLBACK_PREFIX_DIRECTIVE}"))
    app.add_handler(CallbackQueryHandler(h.handle_insights_summary, pattern=f"^{CALLBACK_PREFIX_INSIGHTS_SUMMARY}"))
    app.add_handler(CallbackQueryHandler(h.handle_insights_ask, pattern=f"^{CALLBACK_PREFIX_INSIGHTS_ASK}"))
    app.add_handler(CallbackQueryHandler(h.handle_delete, pattern=f"^{CALLBACK_PREFIX_DELETE}"))
    app.add_handler(CallbackQueryHandler(h.handle_back_to_edit, pattern=f"^{CALLBACK_PREFIX_BACK_EDIT}"))
    app.add_handler(CallbackQueryHandler(h.handle_main_menu, pattern=f"^{CALLBACK_PREFIX_MAIN_MENU}"))
    app.add_handler(CallbackQueryHandler(h.handle_back, pattern=f"^{CALLBACK_PREFIX_BACK}"))

    app.add_error_handler(_error_handler)

    return app
