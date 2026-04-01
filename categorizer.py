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
