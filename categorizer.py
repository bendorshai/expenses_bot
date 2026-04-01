from __future__ import annotations

import logging
from openai import OpenAI

logger = logging.getLogger(__name__)


class Categorizer:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    def categorize(
        self,
        description: str,
        categories: list[str],
        directives: list[str],
    ) -> str:
        if not categories:
            logger.warning("No categories defined — skipping categorization")
            return ""

        categories_block = "\n".join(f"- {c}" for c in categories)
        directives_block = "\n".join(f"- {d}" for d in directives) if directives else "(אין הנחיות)"

        system_prompt = (
            "אתה מערכת סיווג הוצאות. תפקידך לסווג תיאור של הוצאה לאחת מהקטגוריות המוגדרות.\n\n"
            f"קטגוריות אפשריות:\n{categories_block}\n\n"
            f"הנחיות סיווג:\n{directives_block}\n\n"
            "החזר אך ורק את שם הקטגוריה המתאימה, ללא הסבר או טקסט נוסף.\n"
            "אם אף קטגוריה לא מתאימה, החזר את המילה: אחר"
        )

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": description},
                ],
                temperature=0,
                max_tokens=50,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            logger.exception("GPT categorization failed for: %s", description)
            return ""

    def craft_directive(self, feedback: str) -> str:
        """Turn raw user feedback about categorization into a concise directive."""
        system_prompt = (
            "אתה עוזר ליצור הנחיות סיווג עבור מערכת מעקב הוצאות.\n"
            "המשתמש יספק משוב על טעות בסיווג. צור הנחיה קצרה וברורה בעברית "
            "שתנחה סיווגים עתידיים.\n"
            "החזר אך ורק את הנחיית הסיווג, ללא הסבר או טקסט נוסף."
        )
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": feedback},
                ],
                temperature=0,
                max_tokens=150,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            logger.exception("GPT directive crafting failed for: %s", feedback)
            return ""

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
