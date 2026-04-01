#!/usr/bin/env python3
"""One-time script to retroactively load WhatsApp chat expenses into Google Sheets."""

import json
import re
import sys
import time
import logging
from datetime import date
from pathlib import Path

import gspread

from sheets import SheetsClient, _col_letter_to_index
from categorizer import Categorizer

CONFIG_PATH = Path(__file__).parent / "config" / "config.json"

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Raw WhatsApp chat data
# ---------------------------------------------------------------------------

RAW_DATA = """
[12:35, 1/16/2026] : 3.5 קפה
[12:40, 1/16/2026] : 4.5 קפה
[13:50, 1/16/2026] : 37.3 יורו על קקאו דבש ועוד כאלו
[14:01, 1/16/2026] : 11 סלטים
[14:13, 1/16/2026] : 7 חניה
[14:49, 1/16/2026] : 1.2 שוקולד
[15:01, 1/16/2026] : 107 חנות אורגנית
[16:17, 1/17/2026] : 40 סושי
[21:21, 1/19/2026] : 43 קניות פירות ויוגורט ואגוזים
[21:55, 1/19/2026] : 15.5 ג'אנק
[09:50, 1/21/2026] : 3 יורו חלב
[10:13, 1/21/2026] : 15 וודפון
[10:13, 1/21/2026] : 15 חלב ויוגורט
[10:35, 1/22/2026] : 2.5 קפה
[15:31, 1/23/2026] : 15 לחם מחמצת
[15:49, 1/23/2026] : 8.5 סבונים
[21:32, 1/23/2026] : 49 פירות ויוגורט
[21:41, 1/23/2026] : 7.5 אוכלבחוץ רק אני
[14:02, 1/24/2026] : 6.7 קינוחי רואו
[14:02, 1/24/2026] : 7.2 קפה ומאפה
[16:35, 1/24/2026] : 36.7 סלמון שרימפס מלפפונים קישואים 🥒🍤
[20:17, 1/25/2026] : 17 קניות
[21:16, 1/26/2026] : 10 סבון כלים וכפיר
[21:16, 1/26/2026] : 65 דלק
[21:29, 1/27/2026] : 45 ירקות ביצים פירות
[21:29, 1/27/2026] : 30 וודפון
[22:19, 1/27/2026] : 15 אוכל בחוץ
[19:32, 1/29/2026] : 90 קניות
[19:44, 1/29/2026] : 9 השלמות
[19:44, 1/29/2026] : 9 אוכל בחוץ
[13:19, 1/30/2026] : 8 חניה
3 קפה
3 קפה
8 קפה ואוכל
[15:17, 1/30/2026] : 8 קפה ואוכל
[21:52, 1/30/2026] : 70 מסעדה ביחד
[09:55, 1/31/2026] : 15 יורו המרת כספים
[12:52, 1/31/2026] : 119 יורו אוכל אורגני- חלבים קרם קוקוס  אלוורה
[12:52, 1/31/2026] : 19 אזניות
[13:05, 1/31/2026] : 27 לחם ללא גלוטן, קפה, מאפה
[16:56, 1/31/2026] : 11.5 קניות

[19:02, 2/1/2026] : 5.5 קפה וכדור חלבון
[19:19, 2/1/2026] : 24 סלטים
[10:43, 2/3/2026] : 12 קפה היום אתמול ושלשום וחטיפי בריאות
[18:12, 2/3/2026] : 6.5 קפה
[18:13, 2/3/2026] : 37 סלטים
😍
[09:57, 2/4/2026] : 7 קפה הביתה ובטריות
[21:48, 2/4/2026] : ירקות ופירות 44
[21:48, 2/4/2026] : וודפון 20
[12:54, 2/5/2026] : 27 קניות
[20:54, 2/6/2026] : 75 אלפיס
[11:56, 2/7/2026] : 15 קפה וחטיפים לטיול
[14:38, 2/7/2026] : 45 סושי ביחד
[15:12, 2/7/2026] : 96.5 עוף וביצים מחנות אורגנית
[15:35, 2/7/2026] : 12 סלט ומים
[11:09, 2/8/2026] : 3 יוגורטים
[11:28, 2/8/2026] : דלק 50
[14:59, 2/8/2026] : 13 קפה ואוכל בחוץ
[15:09, 2/8/2026] : 37.5 סלטים
[14:35, 2/10/2026] : 22.5 סלטים
[14:35, 2/10/2026] : 16 ירקות הביתה
[18:43, 2/11/2026] : 5 שוקולד לממז
[09:28, 2/12/2026] : 5 קפה
[17:37, 2/12/2026] : 30 סלטים
[10:43, 2/13/2026] : 25 לחמים, קפה ומאפה
[22:37, 2/13/2026] : 20 אוכל בחוץ
[20:41, 2/14/2026] : 30 מסעדה
[20:48, 2/14/2026] : 7 נייר טואלט
[20:14, 2/16/2026] : 46 פירות
[11:30, 2/17/2026] : 10 קפה הביתה
[11:33, 2/17/2026] : 2.5 קפה בחוץ
[21:58, 2/17/2026] : 12 אוכל בחוץ
[08:28, 2/19/2026] : 14 פירות
[12:27, 2/19/2026] : 35 אוכל בשדה
[12:32, 2/19/2026] : 5 יוגורט פיתה
[13:15, 2/19/2026] : 20 יורו קפה ומים
[13:16, 2/19/2026] : 35 אוכל בשדה

מפה זה בשקלים

[12:37, 2/20/2026] : 185 בשקלים טבע כרכור. אבל הייטקזטן מכסה 400 שח מזון בחודש אז לא יוגע איך להתייחס לזה
[12:37, 2/20/2026] : אולי נרשום את זה גם כהותאה וגם כהכנסה?
[13:31, 2/20/2026] : 120 שקל תספורת
[13:43, 2/20/2026] : 33 שקל שייק
[13:06, 2/21/2026] : 100 קפה עם תמר
[22:57, 2/21/2026] : 185 בשקלים טבע כרכור. אבל הייטקזטן מכסה 400 שח מזון בחודש אז לא יוגע איך להתייחס לזה
עוד 41 מיץ מי קוקוס בכיסוי (225 מתוך 400)
[08:51, 2/22/2026] : 150 דלק
[13:13, 2/22/2026] : 85 אוכל (310 מתטך 400)
[14:52, 2/22/2026] : 24 קפה וחטיף תמר
[17:03, 2/22/2026] : 50 ש״ח טעינת רב קו
[17:03, 2/22/2026] : 50 ש״ח רכבות
[18:16, 2/22/2026] : 10 תחבצ
[18:32, 2/22/2026] : 49 אוכל בחוץ (360 מתוך 400)
[18:34, 2/22/2026] : בתאבון מאמי שלי
[18:40, 2/22/2026] : 40 מגן מסך
[08:48, 2/23/2026] : 49 אוכל בחוץ (360 מתוך 400)
78 קפה וסנדוויצים (בערך 40 בפועל)
[17:56, 2/23/2026] : 22 קפה וקישקוש
[19:21, 2/23/2026] : חיימשלי
[23:14, 2/23/2026] : 135 אוכל בחוץ עם אמיר
[16:10, 2/24/2026] : 70 ש״ח מונית
[16:10, 2/24/2026] : 52 ש״ח רכבת לבאר שבע
[18:13, 2/24/2026] : 400 סתימות רופא שיניים
[15:50, 2/25/2026] : 30 שוקולדות
[11:50, 2/26/2026] : 38 טבע כרכור
[17:26, 2/26/2026] : 200 דלק
[11:19, 2/27/2026] : 65 קפה מים ותרומה
[09:36, 2/28/2026] : 76 א בוקר בחוץ
[15:48, 2/28/2026] : 20 שוקולד

[20:44, 3/15/2026] : 423 ש״ח ויטמינים בניצת הדובדבן
לשמור את הקופסאות!!!
[20:45, 3/15/2026] : ברור מה חשבת !
[11:10, 3/16/2026] : 125 טבע כרכור
[11:22, 3/17/2026] : 200 דלק
[11:39, 3/17/2026] : 33 שייק
[19:21, 3/17/2026] : 63 אוכל בחוץ
[08:47, 3/18/2026] : 39 כפפות הביתה ומיץ(אתמול)
[11:18, 3/18/2026] : 33 שייק
[15:35, 3/18/2026] : 130 קפה צהריים
[15:51, 3/18/2026] : 325 חומרים לשיער
[23:13, 3/18/2026] : 20 פיצוחים
[10:27, 3/19/2026] : 60
טבע כרכור
[10:43, 3/19/2026] : 33 שייק
[12:38, 3/19/2026] : 80 אוכל בחוץ
[12:45, 3/19/2026] : 445.5 טבע כרכור
[20:04, 3/19/2026] : 250 תספורת וקפסולות
[20:18, 3/19/2026] : 145 השלמת קניות
[09:28, 3/20/2026] : 10 קפה
[10:38, 3/20/2026] : 26 אוכל בחוץ
[10:49, 3/20/2026] : 70 אצל הדרוזט
[10:49, 3/20/2026] : דרוזי
[13:02, 3/20/2026] : 233 נעליים
[13:20, 3/20/2026] : תחדשי
[13:32, 3/20/2026] : תודה❣️
[16:59, 3/20/2026] : 22
[03:11, 3/21/2026] : 60 מתנה למיה של שמעון
[03:12, 3/21/2026] : 160 קטורות לשמעון (הוא אמור להחזיר על זה)
[20:09, 3/21/2026] : 33 שייק
[20:24, 3/21/2026] : 26 תה ומאפה קטן 🍃
[20:59, 3/21/2026] : 34 עוד שייק
[21:05, 3/21/2026] : תהנה ממזי שממזי
[11:22, 3/22/2026] : 14 קפה
63 אוכל מוכן מטבע כרכור
[18:04, 3/22/2026] : 141 חומרי ניקוי
[23:38, 3/22/2026] : 370 מנקה
[10:10, 3/23/2026] : 98 אוכל מטבע כרכור ושייק
[12:15, 3/23/2026] : 24 מיץ לינאי
[12:15, 3/23/2026] : 15 בטריות
[17:11, 3/23/2026] : 26 תה ומאפה
[10:34, 3/24/2026] : 45 סלטים וקפה בכרכור
[12:40, 3/24/2026] : 35 סלטים קפה כרכור
[15:15, 3/24/2026] : 14 עוגית
[17:21, 3/24/2026] : 33 שוק
[17:21, 3/24/2026] : שייק
[22:36, 3/24/2026] : 200 דלק
[10:24, 3/25/2026] : 14 קפה
125 פירות ושייק בטבע כרכור
[13:47, 3/25/2026] : 20 סיידר תפוחים וכדור שוקולד
[16:50, 3/25/2026] : 46 מטעמים בטבע כרכור
[22:05, 3/25/2026] : 70 בשמים
[22:14, 3/25/2026] : 80 שניצ
[22:18, 3/25/2026] : 70 בשמים
איזה בושם קנית?!
[22:18, 3/25/2026] : רק את הריח שלך אני רוצה להריח
[10:56, 3/26/2026] : 180 טבע כרכור
[13:11, 3/26/2026] : 34 קקאו ומאפין
[15:17, 3/26/2026] : 200 דלק
[15:32, 3/26/2026] : 28 שייק
[15:42, 3/26/2026] : 156 נעליים
[16:48, 3/26/2026] : 146 אוכלים בטבע כרכור
[23:25, 3/26/2026] : 22 כדור גלידה🍨
[13:11, 3/27/2026] : 22 קפה
[13:23, 3/28/2026] : 150 קניות בסופר
[13:34, 3/28/2026] : 100 אוכל דרוזי
[16:38, 3/28/2026] : 75 מתנה לקייטן
[22:26, 3/28/2026] : 200 סווטלודג'
[11:39, 3/29/2026] : 16 קפה
[12:24, 3/29/2026] : 150 קניות לבית
[12:27, 3/29/2026] : 50
[13:28, 3/29/2026] : 61 אוכל בחוץ
[11:23, 3/30/2026] : 230 תספורת
[12:17, 3/30/2026] : 130 פירות
[17:23, 3/30/2026] : 34 ראפ בביינג
[11:48, 3/31/2026] : 33 שייק
[17:00, 3/31/2026] : 60 אוכל בחוץ
"""

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

WHATSAPP_RE = re.compile(
    r"\[(\d{1,2}:\d{2}),\s*(\d{1,2})/(\d{1,2})/(\d{4})\]\s*:\s*(.*)"
)
BARE_NUM_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*$")
AMOUNT_START_RE = re.compile(r"^(\d+(?:\.\d+)?)\s+(.+)$")
AMOUNT_END_RE = re.compile(r"^(.+?)\s+(\d+(?:\.\d+)?)(?:\s+(\S+))?\s*$")

SKIP_PATTERNS = [
    re.compile(r"\(.*(?:מתוך|מתטך)\s*\d+\)"),
    re.compile(r"\(בערך.*בפועל\)"),
]

CURRENCY_TOKENS = {
    "יורו": "יורו",
    "אירו": "יורו",
    "euro": "יורו",
    "eur": "יורו",
    "ש״ח": "שקל",
    'ש"ח': "שקל",
    "שח": "שקל",
    "שקל": "שקל",
    "שקלים": "שקל",
    "בשקלים": "שקל",
}

EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U00002702-\U000027B0"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "\U00002600-\U000026FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002B50"
    "\U0000203C-\U00003299"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "]+",
    flags=re.UNICODE,
)


def clean_description(desc: str) -> str:
    if ". אבל" in desc:
        desc = desc.split(". אבל")[0]
    desc = re.sub(r"\s*\(הוא אמור להחזיר על זה\)", "", desc)
    desc = re.sub(r"\s*\(אתמול\)", "", desc)
    desc = EMOJI_RE.sub("", desc)
    desc = re.sub(r"\s+", " ", desc).strip()
    return desc


def parse_expense_text(text: str, currency_mode: str):
    """Extract (amount, description, currency) or None."""
    text = text.strip()
    if not text:
        return None

    for pat in SKIP_PATTERNS:
        if pat.search(text):
            return None

    if not re.search(r"\d", text):
        return None

    m = AMOUNT_START_RE.match(text)
    if m:
        amount = float(m.group(1))
        rest = m.group(2).strip()
        words = rest.split(maxsplit=1)
        if words:
            cur = CURRENCY_TOKENS.get(words[0])
            if cur:
                desc = words[1].strip() if len(words) > 1 else ""
                desc = clean_description(desc)
                return (amount, desc, cur) if desc else None
        desc = clean_description(rest)
        return (amount, desc, currency_mode) if desc else None

    m = AMOUNT_END_RE.match(text)
    if m:
        desc = m.group(1).strip()
        amount = float(m.group(2))
        cur_word = m.group(3)
        cur = CURRENCY_TOKENS.get(cur_word) if cur_word else None
        desc = clean_description(desc)
        return (amount, desc, cur or currency_mode) if desc else None

    return None


def parse_all() -> list[tuple[date, float, str, str]]:
    lines = RAW_DATA.strip().split("\n")
    expenses: list[tuple[date, float, str, str]] = []
    current_date: date | None = None
    currency_mode = "יורו"
    seen_bsamim_325 = False

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1

        if not line:
            continue

        if "מפה זה בשקלים" in line:
            currency_mode = "שקל"
            continue

        m = WHATSAPP_RE.match(line)
        if m:
            month, day, year = int(m.group(2)), int(m.group(3)), int(m.group(4))
            current_date = date(year, month, day)
            text = m.group(5).strip()
        else:
            text = line

        if current_date is None:
            continue

        # --- manual corrections ---
        if current_date == date(2026, 3, 20) and text == "70 אצל הדרוזט":
            text = "70 אצל הדרוזי"
        elif current_date == date(2026, 3, 24) and text == "33 שוק":
            text = "33 שייק"
        elif current_date == date(2026, 3, 25) and text == "70 בשמים":
            if seen_bsamim_325:
                continue
            seen_bsamim_325 = True

        # bare number -> try merging with next continuation line
        if BARE_NUM_RE.match(text):
            if i < len(lines):
                next_line = lines[i].strip()
                if (
                    next_line
                    and not WHATSAPP_RE.match(next_line)
                    and not BARE_NUM_RE.match(next_line)
                ):
                    text = f"{text} {next_line}"
                    i += 1
                else:
                    continue
            else:
                continue

        result = parse_expense_text(text, currency_mode)
        if result:
            amount, desc, currency = result
            expenses.append((current_date, amount, desc, currency))

    return expenses


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    dry_run = "--dry-run" in sys.argv

    expenses = parse_all()
    logger.info("Parsed %d expenses", len(expenses))

    if dry_run:
        for i, (d, amount, desc, cur) in enumerate(expenses, 1):
            print(f"{i:3d}. [{d.strftime('%d/%m/%Y')}] {amount:>8} {cur:<5} {desc}")
        print(f"\nTotal: {len(expenses)} expenses")
        eur = [e for e in expenses if e[3] == "יורו"]
        ils = [e for e in expenses if e[3] == "שקל"]
        print(f"EUR: {len(eur)}  (total {sum(e[1] for e in eur):.2f})")
        print(f"ILS: {len(ils)}  (total {sum(e[1] for e in ils):.2f})")
        return

    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)

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

    categorizer = Categorizer(api_key=openai_cfg["api_key"])

    # Step 1: batch-append all rows
    logger.info("Step 1: Appending %d rows to sheet...", len(expenses))
    ws = sheets_client._get_worksheet()
    existing_rows = len(ws.get_all_values())

    all_rows = []
    for exp_date, amount, desc, currency in expenses:
        values = {
            "תאריך": exp_date.strftime("%d/%m/%Y"),
            "תיאור": desc,
            "חובה": str(amount),
            "זכות": "0",
            "תנועה": str(-amount),
            "מטבע": currency,
        }
        all_rows.append(sheets_client._build_row(values))

    ws.append_rows(all_rows, value_input_option="USER_ENTERED", table_range="A1")
    start_row = existing_rows + 1
    logger.info("Rows written: %d–%d", start_row, start_row + len(expenses) - 1)

    # Step 2: categorize via GPT
    logger.info("Step 2: Categorizing %d expenses via GPT...", len(expenses))
    categories_list = sheets_client.get_categories()
    directives = sheets_client.get_directives()

    cat_results: list[str] = []
    for i, (_, _, desc, _) in enumerate(expenses):
        cat = categorizer.categorize(desc, categories_list, directives)
        cat_results.append(cat)
        print(f"  [{i + 1}/{len(expenses)}] {desc} -> {cat or 'N/A'}")
        time.sleep(0.1)

    # Step 3: batch-update categories
    logger.info("Step 3: Writing categories to sheet...")
    cat_col_letter = sheets_client._col_letter_for("סיווג")
    cat_col_idx = _col_letter_to_index(cat_col_letter) + 1  # gspread Cell is 1-based

    cells = []
    for i, cat in enumerate(cat_results):
        if cat:
            cells.append(gspread.Cell(start_row + i, cat_col_idx, cat))

    if cells:
        ws.update_cells(cells, value_input_option="USER_ENTERED")

    categorized = sum(1 for c in cat_results if c)
    logger.info(
        "Done! Loaded %d expenses, categorized %d.",
        len(expenses),
        categorized,
    )


if __name__ == "__main__":
    main()
