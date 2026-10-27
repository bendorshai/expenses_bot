from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    filters,
)

from datetime import time, timedelta

from sheets import SheetsClient
from categorizer import Categorizer
from storage import MongoStorage
from budget_alerts import BudgetAlerter
from parsing import build_currency_lookup, israel_today, IL_TZ
from keyboards import (
    OK_HAND,
    CALLBACK_PREFIX_EDIT, CALLBACK_PREFIX_EDIT_DESC, CALLBACK_PREFIX_EDIT_AMT,
    CALLBACK_PREFIX_EDIT_DATE, CALLBACK_PREFIX_EDIT_CAT, CALLBACK_PREFIX_EDIT_CUR,
    CALLBACK_PREFIX_CAT, CALLBACK_PREFIX_CUR_SET, CALLBACK_PREFIX_CUR_MENU,
    CALLBACK_PREFIX_CUR_MODE,
    CALLBACK_PREFIX_UPDATE, CALLBACK_PREFIX_DELETE, CALLBACK_PREFIX_DIRECTIVE,
    CALLBACK_PREFIX_SUGGEST_DIR, CALLBACK_PREFIX_DECLINE_DIR,
    CALLBACK_PREFIX_CONFIRM_CAT, CALLBACK_PREFIX_REJECT_CAT,
    CALLBACK_PREFIX_INSIGHTS_SUMMARY, CALLBACK_PREFIX_INSIGHTS_ASK,
    CALLBACK_PREFIX_BACK, CALLBACK_PREFIX_BACK_EDIT, CALLBACK_PREFIX_MAIN_MENU,
)
from handlers import ExpenseHandlers

logger = logging.getLogger(__name__)


def _make_error_handler(mongo_storage: MongoStorage):
    async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("Unhandled exception while processing update:", exc_info=context.error)

        chat_id = None
        message_text = ""
        update_id = None
        handler_name = ""
        if isinstance(update, Update):
            update_id = update.update_id
            if update.effective_chat:
                chat_id = update.effective_chat.id
            if update.effective_message and update.effective_message.text:
                message_text = update.effective_message.text
            if update.callback_query and update.callback_query.data:
                handler_name = f"callback:{update.callback_query.data}"
            elif update.effective_message:
                handler_name = "message"

        try:
            mongo_storage.log_error(
                error=context.error,
                handler=handler_name,
                chat_id=chat_id,
                message_text=message_text,
                update_id=update_id,
            )
        except Exception:
            logger.exception("Failed to log error to MongoDB")

        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text("❌ שגיאה פנימית. נסה שוב.")
            except Exception:
                pass

    return _error_handler


async def retroload(
    app: Application,
    chat_id: int,
    sheets_client: SheetsClient,
    categorizer: Categorizer,
    currencies: list[str],
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

    today_str = israel_today().strftime("%d/%m/%Y")
    categories = sheets_client.get_categories()
    directives = sheets_client.get_directives()
    handlers = app.bot_data.get("handlers")
    chat_data = app._chat_data[chat_id]
    processed = 0

    for update in updates:
        msg = update.message
        if not msg or not msg.text or msg.chat_id != chat_id:
            continue

        result = categorizer.parse_message(
            text=msg.text,
            categories=categories,
            directives=directives,
            currencies=currencies,
            default_currency=default_currency,
            today_str=today_str,
        )

        if result.type != "expenses" or not result.expenses:
            logger.info("Retroload: skipping non-expense message: %s", msg.text[:80])
            continue

        try:
            # Reuse the live flow: record each expense as "אחר" with a confirmation prompt.
            ack = await handlers._record_and_confirm(result.expenses, msg.from_user, msg, chat_data)
            if ack is not None:
                processed += len(result.expenses)
        except Exception:
            logger.exception("Retroload: failed to process message %d", msg.message_id)

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
    budget_cfg: dict | None = None,
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
    app.add_handler(CallbackQueryHandler(h.handle_suggest_directive, pattern=f"^{CALLBACK_PREFIX_SUGGEST_DIR}"))
    app.add_handler(CallbackQueryHandler(h.handle_decline_directive, pattern=f"^{CALLBACK_PREFIX_DECLINE_DIR}"))
    app.add_handler(CallbackQueryHandler(h.handle_confirm_category, pattern=f"^{CALLBACK_PREFIX_CONFIRM_CAT}"))
    app.add_handler(CallbackQueryHandler(h.handle_reject_category, pattern=f"^{CALLBACK_PREFIX_REJECT_CAT}"))
    app.add_handler(CallbackQueryHandler(h.handle_insights_summary, pattern=f"^{CALLBACK_PREFIX_INSIGHTS_SUMMARY}"))
    app.add_handler(CallbackQueryHandler(h.handle_insights_ask, pattern=f"^{CALLBACK_PREFIX_INSIGHTS_ASK}"))
    app.add_handler(CallbackQueryHandler(h.handle_delete, pattern=f"^{CALLBACK_PREFIX_DELETE}"))
    app.add_handler(CallbackQueryHandler(h.handle_back_to_edit, pattern=f"^{CALLBACK_PREFIX_BACK_EDIT}"))
    app.add_handler(CallbackQueryHandler(h.handle_main_menu, pattern=f"^{CALLBACK_PREFIX_MAIN_MENU}"))
    app.add_handler(CallbackQueryHandler(h.handle_back, pattern=f"^{CALLBACK_PREFIX_BACK}"))

    app.add_error_handler(_make_error_handler(mongo_storage))

    async def _refresh_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.info("Background job: refreshing sheets data and category popularity")
        h.refresh_all_data()

    app.job_queue.run_repeating(_refresh_job, interval=timedelta(days=7), first=timedelta(seconds=10))

    # Daily budget-threshold alerts (opt-in via config). Reads budget usage from
    # the card_to_sheet API and notifies when a category crosses 50/75/100%.
    if budget_cfg and budget_cfg.get("enabled", True) \
            and budget_cfg.get("api_url") and budget_cfg.get("api_token"):
        alerter = BudgetAlerter(
            mongo_storage=mongo_storage,
            chat_id=chat_id,
            api_url=budget_cfg["api_url"],
            api_token=budget_cfg["api_token"],
        )

        async def _budget_alert_job(context: ContextTypes.DEFAULT_TYPE) -> None:
            logger.info("Background job: checking budget thresholds")
            await alerter.run(context.bot)

        app.job_queue.run_daily(_budget_alert_job, time=time(hour=9, tzinfo=IL_TZ))
        logger.info("Budget alerts enabled — daily check at 09:00 Israel time")
    else:
        logger.info("Budget alerts disabled (no budget_alerts config)")

    # Expose the handler instance so retroload can reuse its record-and-confirm logic.
    app.bot_data["handlers"] = h

    return app
