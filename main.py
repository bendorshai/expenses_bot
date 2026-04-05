import json
import logging
import os
import sys
from pathlib import Path

from sheets import SheetsClient
from categorizer import Categorizer
from storage import MongoStorage
from bot import create_bot, retroload
from parsing import build_currency_lookup

VERSION = "0.1.6"
VERSION_NOTES = "הצעה להוסיף הנחיית סיווג אחרי שינוי קטגוריה ידני"
CONFIG_PATH = Path(__file__).parent / "config" / "config.json"

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _parse_last_json(text: str) -> dict:
    """Parse the last valid JSON object from text, handling Railway's duplicate-append bug."""
    decoder = json.JSONDecoder()
    text = text.strip()
    result = None
    pos = 0
    while pos < len(text):
        try:
            obj, end = decoder.raw_decode(text, pos)
            result = obj
            pos = end
        except json.JSONDecodeError:
            pos += 1
    if result is None:
        raise json.JSONDecodeError("No valid JSON found", text, 0)
    return result


def load_config() -> dict:
    env_json = os.environ.get("CONFIG2_JSON") or os.environ.get("CONFIG_JSON")
    if env_json:
        logger.info("Loading config from environment variable")
        return _parse_last_json(env_json)
    if not CONFIG_PATH.exists():
        logger.error("Config file not found: %s", CONFIG_PATH)
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return _parse_last_json(f.read())


def main():
    cfg = load_config()

    tg = cfg["telegram"]
    gs = cfg["google_sheets"]
    columns = cfg["table_columns"]
    openai_cfg = cfg["openai"]

    sheets_client = SheetsClient(
        credentials_file=gs["credentials_file"],
        sheet_id=gs["sheet_id"],
        tab_name=gs["tab_name"],
        table_columns=columns,
        categories_tab_name=gs.get("categories_tab_name", "categories"),
        directives_tab_name=gs.get("directives_tab_name", "directives"),
        currencies_tab_name=gs.get("currencies_tab_name", "currencies"),
    )
    logger.info("Google Sheets client ready (sheet: %s, tab: %s)", gs["sheet_id"], gs["tab_name"])

    currencies = sheets_client.get_currencies()
    default_currency = currencies[0] if currencies else "שקל"
    logger.info("Currencies loaded: %s (default: %s)", currencies, default_currency)

    categorizer = Categorizer(api_key=openai_cfg["api_key"])
    logger.info("GPT categorizer ready")

    mongo_cfg = cfg["mongodb"]
    mongo_storage = MongoStorage(uri=mongo_cfg["uri"], db_name=mongo_cfg["db_name"])

    currency_lookup = build_currency_lookup(currencies)

    app = create_bot(tg["bot_token"], tg["chat_id"], sheets_client, categorizer, currencies, default_currency, mongo_storage)

    async def post_init(application):
        saved_currencies = mongo_storage.get_all_user_currencies()
        if saved_currencies:
            if tg["chat_id"] not in application._chat_data:
                application._chat_data[tg["chat_id"]] = {}
            application._chat_data[tg["chat_id"]]["user_currencies"] = saved_currencies
            logger.info("Loaded %d user currency preferences from MongoDB", len(saved_currencies))
        await retroload(application, tg["chat_id"], sheets_client, categorizer, currency_lookup, default_currency)
        try:
            await application.bot.send_message(
                chat_id=tg["chat_id"],
                text=f"🚀 עלתה גרסה חדשה: {VERSION}\n{VERSION_NOTES}",
            )
        except Exception:
            logger.exception("Failed to send startup message")

    app.post_init = post_init

    webhook_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")

    if webhook_domain:
        port = int(os.environ.get("PORT", 8443))
        webhook_url = f"https://{webhook_domain}/webhook"
        logger.info("Bot starting — webhook mode at %s (port %d), chat %s", webhook_url, port, tg["chat_id"])
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="webhook",
            webhook_url=webhook_url,
        )
    else:
        logger.info("Bot starting — polling mode, chat %s", tg["chat_id"])
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
