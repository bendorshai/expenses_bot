from __future__ import annotations

import logging
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ParsedExpense(BaseModel):
    amount: float
    description: str
    category: str
    currency: str
    date: str | None


class ParseResult(BaseModel):
    type: Literal["expenses", "query", "unknown"]
    expenses: list[ParsedExpense] | None = None
    query: str | None = None


class Categorizer:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    def parse_message(
        self,
        text: str,
        categories: list[str],
        directives: list[str],
        currencies: list[str],
        default_currency: str,
        today_str: str,
    ) -> ParseResult:
        """Parse a user message using GPT: extract expenses with categories, or identify as a query."""
        categories_block = "\n".join(f"- {c}" for c in categories) if categories else "(אין קטגוריות)"
        directives_block = "\n".join(f"- {d}" for d in directives) if directives else "(אין הנחיות)"
        currencies_str = ", ".join(currencies) if currencies else default_currency

        system_prompt = (
            "אתה מערכת ניתוח הודעות למעקב הוצאות. תפקידך לנתח הודעת טקסט מהמשתמש ולהחזיר JSON מובנה.\n\n"
            "סוגי הודעות:\n"
            '1. "expenses" — הודעה שמכילה הוצאה אחת או יותר (כל שורה = הוצאה)\n'
            '2. "query" — שאלה או בקשה על הנתונים (למשל "כמה הוצאתי במרץ?")\n'
            '3. "unknown" — לא ברור מה המשתמש רוצה\n\n'
            "פורמטים אפשריים להוצאה:\n"
            '- <סכום> <תיאור>          → "50 חלב"\n'
            '- <תיאור> <סכום>          → "חלב 50"\n'
            '- <סכום> <מטבע> <תיאור>  → "50 דולר מתנה"\n'
            '- <תיאור> <סכום> <מטבע>  → "מתנה 50 דולר"\n'
            '- ניתן לציין תאריך: "אתמול", "שלשום", או dd/mm/yyyy בתחילת או סוף השורה\n'
            "- אם המשתמש כותב משהו בסוגריים, זו הנחיה קריטית לסיווג ואינה חלק מהתיאור.\n"
            '  למשל: "מונית 20 (טיסות)" — התיאור הוא "מונית", הסכום 20,\n'
            '  אבל הסיווג צריך להתבסס על "טיסות".\n\n'
            f"קטגוריות אפשריות:\n{categories_block}\n\n"
            f"הנחיות סיווג:\n{directives_block}\n\n"
            f"מטבעות זמינים: {currencies_str}\n"
            f"מטבע ברירת מחדל: {default_currency}\n\n"
            f"התאריך של היום: {today_str}\n"
            "אם לא צוין תאריך, החזר null בשדה date.\n"
            "אם צוין תאריך (אתמול, שלשום, או תאריך מספרי), חשב והחזר בפורמט dd/mm/yyyy.\n"
        )

        try:
            response = self.client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                response_format=ParseResult,
                temperature=0,
            )
            result = response.choices[0].message.parsed
            if result is None:
                logger.warning("GPT parse returned None for: %s", text[:80])
                return ParseResult(type="unknown")
            return result
        except Exception:
            logger.exception("GPT parse_message failed for: %s", text[:80])
            return ParseResult(type="unknown")

    def analyze_expenses(self, question: str, expenses_csv: str) -> str:
        """Answer a user question about their expense data."""
        system_prompt = (
            "אתה אנליסט נתונים של מערכת מעקב הוצאות אישית.\n"
            "הנתונים מוצגים בפורמט CSV עם העמודות: תאריך, תיאור, סכום, סיווג, מטבע.\n"
            "ענה על שאלות המשתמש בצורה מדויקת ומבוססת נתונים.\n"
            "ענה בעברית. היה תמציתי וברור. השתמש במספרים ותאריכים מדויקים מהנתונים."
        )
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"הנתונים:\n{expenses_csv}\n\nשאלה: {question}"},
                ],
                temperature=0,
                max_tokens=1000,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            logger.exception("GPT expense analysis failed for: %s", question)
            return ""
