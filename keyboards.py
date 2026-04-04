from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

THUMBS_UP = "\U0001F44D"
OK_HAND = "\U0001F44C"

CALLBACK_PREFIX_EDIT = "edit_"
CALLBACK_PREFIX_EDIT_DESC = "edesc_"
CALLBACK_PREFIX_EDIT_AMT = "eamt_"
CALLBACK_PREFIX_EDIT_DATE = "edate_"
CALLBACK_PREFIX_EDIT_CAT = "ecat_"
CALLBACK_PREFIX_EDIT_CUR = "ecur_"
CALLBACK_PREFIX_CAT = "cat_"
CALLBACK_PREFIX_CUR_SET = "curs_"
CALLBACK_PREFIX_CUR_MENU = "curm_"
CALLBACK_PREFIX_UPDATE = "upd_"
CALLBACK_PREFIX_DELETE = "del_"
CALLBACK_PREFIX_READD = "readd_"
CALLBACK_PREFIX_DIRECTIVE = "dir_"
CALLBACK_PREFIX_INSIGHTS_SUMMARY = "isum_"
CALLBACK_PREFIX_INSIGHTS_ASK = "iask_"
CALLBACK_PREFIX_BACK = "back_"
CALLBACK_PREFIX_BACK_EDIT = "bked_"
CALLBACK_PREFIX_MAIN_MENU = "mmenu_"


def make_edit_button(row_number: int, description: str) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(f"עריכה — {description}", callback_data=f"{CALLBACK_PREFIX_EDIT}{row_number}")]


def make_edit_menu_keyboard(row_number: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("תיאור", callback_data=f"{CALLBACK_PREFIX_EDIT_DESC}{row_number}"),
            InlineKeyboardButton("סכום", callback_data=f"{CALLBACK_PREFIX_EDIT_AMT}{row_number}"),
        ],
        [
            InlineKeyboardButton("מטבע", callback_data=f"{CALLBACK_PREFIX_EDIT_CUR}{row_number}"),
            InlineKeyboardButton("תאריך", callback_data=f"{CALLBACK_PREFIX_EDIT_DATE}{row_number}"),
        ],
        [
            InlineKeyboardButton("סיווג", callback_data=f"{CALLBACK_PREFIX_EDIT_CAT}{row_number}"),
            InlineKeyboardButton("הנחיה לסיווג עתידי", callback_data=f"{CALLBACK_PREFIX_DIRECTIVE}{row_number}"),
        ],
        [InlineKeyboardButton("מחיקה", callback_data=f"{CALLBACK_PREFIX_DELETE}{row_number}")],
        [InlineKeyboardButton("חזור", callback_data=f"{CALLBACK_PREFIX_BACK}")],
    ])


def make_cancel_keyboard(row_number: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ביטול", callback_data=f"{CALLBACK_PREFIX_BACK_EDIT}{row_number}")],
    ])


def make_categories_keyboard(row_number: int, categories: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    for cat in categories:
        buttons.append([InlineKeyboardButton(cat, callback_data=f"{CALLBACK_PREFIX_CAT}{row_number}:{cat}")])
    buttons.append([InlineKeyboardButton("חזור", callback_data=f"{CALLBACK_PREFIX_BACK_EDIT}{row_number}")])
    return InlineKeyboardMarkup(buttons)


def make_currency_keyboard(row_number: int, currency_list: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    for cur in currency_list:
        buttons.append([InlineKeyboardButton(cur, callback_data=f"{CALLBACK_PREFIX_CUR_SET}{row_number}:{cur}")])
    buttons.append([InlineKeyboardButton("חזור", callback_data=f"{CALLBACK_PREFIX_BACK_EDIT}{row_number}")])
    return InlineKeyboardMarkup(buttons)


def make_insights_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 סיכום חודשי", callback_data=f"{CALLBACK_PREFIX_INSIGHTS_SUMMARY}0")],
        [InlineKeyboardButton("🔍 שאל שאלה על ההוצאות", callback_data=f"{CALLBACK_PREFIX_INSIGHTS_ASK}0")],
        [InlineKeyboardButton("חזור לתפריט", callback_data=f"{CALLBACK_PREFIX_MAIN_MENU}home")],
    ])


def make_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 סיכום חודשי", callback_data=f"{CALLBACK_PREFIX_INSIGHTS_SUMMARY}0"),
            InlineKeyboardButton("🔍 שאל שאלה", callback_data=f"{CALLBACK_PREFIX_INSIGHTS_ASK}0"),
        ],
        [
            InlineKeyboardButton("💱 מצב מטבע", callback_data=f"{CALLBACK_PREFIX_MAIN_MENU}currency"),
            InlineKeyboardButton("📋 הנחיות סיווג", callback_data=f"{CALLBACK_PREFIX_MAIN_MENU}directives"),
        ],
        [InlineKeyboardButton("חזור", callback_data=f"{CALLBACK_PREFIX_MAIN_MENU}home")],
    ])


def base_text(text: str) -> str:
    """Strip any status suffix (everything after the first double newline)."""
    return text.split("\n\n")[0]
