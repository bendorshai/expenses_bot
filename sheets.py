from __future__ import annotations

import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _col_letter_to_index(letter: str) -> int:
    return ord(letter.upper()) - ord("A")


class SheetsClient:
    def __init__(
        self,
        credentials_file: str,
        sheet_id: str,
        tab_name: str,
        table_columns: dict[str, str],
        categories_tab_name: str = "categories",
        directives_tab_name: str = "directives",
        currencies_tab_name: str = "currencies",
    ):
        creds = Credentials.from_service_account_file(credentials_file, scopes=SCOPES)
        self.gc = gspread.authorize(creds)
        self.sheet_id = sheet_id
        self.tab_name = tab_name
        self.table_columns = table_columns
        self.total_cols = max(_col_letter_to_index(c) for c in table_columns) + 1
        self.categories_tab_name = categories_tab_name
        self.directives_tab_name = directives_tab_name
        self.currencies_tab_name = currencies_tab_name

    def _get_spreadsheet(self) -> gspread.Spreadsheet:
        return self.gc.open_by_key(self.sheet_id)

    def _get_worksheet(self) -> gspread.Worksheet:
        spreadsheet = self._get_spreadsheet()
        try:
            return spreadsheet.worksheet(self.tab_name)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(
                title=self.tab_name, rows=1000, cols=self.total_cols,
            )
            header = self._build_row_by_headers()
            ws.append_row(header, value_input_option="USER_ENTERED", table_range="A1")
            ws.format("1", {"textFormat": {"bold": True}})
            return ws

    def _build_row_by_headers(self) -> list[str]:
        row = [""] * self.total_cols
        for col_letter, header_name in self.table_columns.items():
            row[_col_letter_to_index(col_letter)] = header_name
        return row

    def _build_row(self, values: dict[str, str]) -> list[str]:
        """Build a row array placing values at the correct column positions.

        Args:
            values: mapping of Hebrew column name -> cell value
        """
        col_name_to_index = {
            name: _col_letter_to_index(letter)
            for letter, name in self.table_columns.items()
        }
        row = [""] * self.total_cols
        for col_name, value in values.items():
            if col_name in col_name_to_index:
                row[col_name_to_index[col_name]] = value
        return row

    def _col_letter_for(self, col_name: str) -> str | None:
        for letter, name in self.table_columns.items():
            if name == col_name:
                return letter
        return None

    def append_expense(
        self,
        amount: float,
        description: str,
        currency: str = "שקל",
        expense_date: date | None = None,
    ) -> int:
        """Append an expense row and return the 1-based row number it was written to."""
        ws = self._get_worksheet()
        d = expense_date or datetime.now().date()

        values = {
            "תאריך": d.strftime("%d/%m/%Y"),
            "תיאור": description,
            "חובה": str(amount),
            "זכות": "0",
            "תנועה": str(-amount),
            "מטבע": currency,
        }

        row = self._build_row(values)
        result = ws.append_row(row, value_input_option="USER_ENTERED", table_range="A1")
        updated_range = result.get("updates", {}).get("updatedRange", "")
        if updated_range and "!" in updated_range:
            cell_ref = updated_range.split("!")[-1].split(":")[0]
            row_digits = "".join(c for c in cell_ref if c.isdigit())
            if row_digits:
                return int(row_digits)
        return len(ws.get_all_values())

    def update_cell_by_name(self, row_number: int, col_name: str, value: str) -> None:
        col_letter = self._col_letter_for(col_name)
        if col_letter is None:
            return
        ws = self._get_worksheet()
        ws.update_acell(f"{col_letter}{row_number}", value)

    def update_category(self, row_number: int, category: str) -> None:
        self.update_cell_by_name(row_number, "סיווג", category)

    def update_currency(self, row_number: int, currency: str) -> None:
        self.update_cell_by_name(row_number, "מטבע", currency)

    def update_description(self, row_number: int, description: str) -> None:
        self.update_cell_by_name(row_number, "תיאור", description)

    def update_amount(self, row_number: int, amount: float) -> None:
        self.update_cell_by_name(row_number, "חובה", str(amount))
        self.update_cell_by_name(row_number, "תנועה", str(-amount))

    def update_date(self, row_number: int, expense_date: date) -> None:
        self.update_cell_by_name(row_number, "תאריך", expense_date.strftime("%d/%m/%Y"))

    def delete_row(self, row_number: int) -> None:
        """Clear all cells in a row (avoids shifting other rows)."""
        ws = self._get_worksheet()
        empty_row = [""] * self.total_cols
        ws.update(f"A{row_number}", [empty_row], value_input_option="RAW")

    def get_expense_data(self, row_number: int) -> dict[str, str]:
        """Read a row and return a dict of column_name -> value."""
        ws = self._get_worksheet()
        row_values = ws.row_values(row_number)
        col_index_to_name = {
            _col_letter_to_index(letter): name
            for letter, name in self.table_columns.items()
        }
        result = {}
        for idx, val in enumerate(row_values):
            if idx in col_index_to_name:
                result[col_index_to_name[idx]] = val
        return result

    def get_categories(self) -> list[str]:
        """Read all category names from column A of the categories tab."""
        spreadsheet = self._get_spreadsheet()
        try:
            ws = spreadsheet.worksheet(self.categories_tab_name)
        except gspread.WorksheetNotFound:
            return []
        values = ws.col_values(1)
        return [v.strip() for v in values if v.strip()]

    def get_directives(self) -> list[str]:
        """Read all directives from column A of the directives tab."""
        spreadsheet = self._get_spreadsheet()
        try:
            ws = spreadsheet.worksheet(self.directives_tab_name)
        except gspread.WorksheetNotFound:
            return []
        values = ws.col_values(1)
        return [v.strip() for v in values if v.strip()]

    def get_currencies(self) -> list[str]:
        """Read all currency names from column A of the currencies tab.
        First row is the default currency."""
        spreadsheet = self._get_spreadsheet()
        try:
            ws = spreadsheet.worksheet(self.currencies_tab_name)
        except gspread.WorksheetNotFound:
            return []
        values = ws.col_values(1)
        return [v.strip() for v in values if v.strip()]
