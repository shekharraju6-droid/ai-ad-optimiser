"""Interim Google Sheets report formatter for Shyam Steel.

This service creates a pre-formatted Google Sheet with the standard
InsightDesk report layout (Table 1-5 headers, totals, grand totals,
campus sections). It does not pull live data yet — it builds the
structure so the client can review and later populate manually or
via auto-sync.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

logger = logging.getLogger("AdOptima")


class ShyamSteelSheetsFormatter:
    """Create a formatted Google Sheet for Shyam Steel reports."""

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

    def __init__(self, service_account_json: str, spreadsheet_id: Optional[str] = None):
        self.service_account_info = json.loads(service_account_json)
        self.credentials = Credentials.from_service_account_info(
            self.service_account_info, scopes=self.SCOPES
        )
        self.service = build("sheets", "v4", credentials=self.credentials)
        self.spreadsheet_id = spreadsheet_id

    def create_or_format(self) -> Dict[str, Any]:
        """Create a new spreadsheet or format an existing one."""
        if not self.spreadsheet_id:
            spreadsheet = self.service.spreadsheets().create(
                body={"properties": {"title": "Shyam Steel - Digital Marketing MIS"}}
            ).execute()
            self.spreadsheet_id = spreadsheet["spreadsheetId"]

        self._prepare_sheets()
        self._apply_formats()

        return {
            "spreadsheet_id": self.spreadsheet_id,
            "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}/edit",
            "message": "Formatted report structure created for Shyam Steel.",
        }

    def _prepare_sheets(self):
        """Ensure required sheets exist."""
        # Get existing sheets
        spreadsheet = self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        existing_titles = {s["properties"]["title"]: s["properties"]["sheetId"] for s in spreadsheet["sheets"]}

        required_sheets = ["Course Performance", "Application MIS", "Budget MIS"]
        for title in required_sheets:
            if title not in existing_titles:
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
                ).execute()

    def _apply_formats(self):
        """Write headers and apply formatting to each sheet."""
        self._format_course_performance()
        self._format_application_mis()
        self._format_budget_mis()

    def _format_course_performance(self):
        sheet = "Course Performance"
        # Table 1 — Daily
        values = [
            ["DSU Course Performance Report"],
            [],
            ["Table 1: Daily Performance"],
            ["Course", "Lead", "CPL", "Spend"],
            ["B.Tech", "", "", ""],
            ["Total", "=SUM(B5:B5)", "", "=SUM(D5:D5)"],
            [],
            ["Table 2: Cumulative Performance"],
            ["Course", "Lead", "CPL", "Spend"],
            ["B.Tech", "", "", ""],
            ["Total", "=SUM(B10:B10)", "", "=SUM(D10:D10)"],
        ]
        self._write_values(sheet, "A1", values)
        self._bold_row(sheet, 3)  # Table 1 title
        self._header_row(sheet, 3)  # Header row index 3 (0-based)
        self._bold_row(sheet, 8)  # Table 2 title
        self._header_row(sheet, 8)  # Header row index 8

    def _format_application_mis(self):
        sheet = "Application MIS"
        values = [
            ["Shyam Steel - Application Submitted and CPA by Campus/Program"],
            [],
            ["CAMPUS - 4 PROGRAMMES"],
            ["Course", "Apps", "CPA", "Spend", "Target"],
            ["B.Tech", "", "", "", ""],
            ["Total", "=SUM(B5:B5)", "", "=SUM(D5:D5)", "=SUM(E5:E5)"],
            [],
            ["CAMPUS - 3 PROGRAMMES"],
            ["Course", "Apps", "CPA", "Spend", "Target"],
            ["BSc Data Science", "", "", "", ""],
            ["Total", "=SUM(B10:B10)", "", "=SUM(D10:D10)", "=SUM(E10:E10)"],
            [],
            ["GRAND TOTAL", "=SUM(B6:B6,B12:B12)", "", "=SUM(D6:D6,D12:D12)", "=SUM(E6:E6,E12:E12)"],
        ]
        self._write_values(sheet, "A1", values)
        self._header_row(sheet, 0)
        self._section_row(sheet, 2)
        self._header_row(sheet, 3)
        self._section_row(sheet, 7)
        self._header_row(sheet, 8)
        self._grand_total_row(sheet, 12)

    def _format_budget_mis(self):
        sheet = "Budget MIS"
        values = [
            ["Shyam Steel - Budget MIS by Campus/Program"],
            [],
            ["CAMPUS - 4 PROGRAMMES"],
            ["Dept", "Course", "Status", "Budget", "Spend", "Remaining"],
            ["", "B.Tech", "Live", "", "", ""],
            ["Total", "", "", "=SUM(D5:D5)", "=SUM(E5:E5)", "=SUM(F5:F5)"],
            [],
            ["CAMPUS - 3 PROGRAMMES"],
            ["Dept", "Course", "Status", "Budget", "Spend", "Remaining"],
            ["", "BSc Data Science", "Live", "", "", ""],
            ["Total", "", "", "=SUM(D10:D10)", "=SUM(E10:E10)", "=SUM(F10:F10)"],
            [],
            ["GRAND TOTAL", "", "", "=SUM(D6:D6,D11:D11)", "=SUM(E6:E6,E11:E11)", "=SUM(F6:F6,F11:F11)"],
        ]
        self._write_values(sheet, "A1", values)
        self._header_row(sheet, 0)
        self._section_row(sheet, 2)
        self._header_row(sheet, 3)
        self._section_row(sheet, 7)
        self._header_row(sheet, 8)
        self._grand_total_row(sheet, 12)

    def _write_values(self, sheet: str, range_name: str, values: List[List[str]]):
        body = {"values": values}
        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{sheet}!{range_name}",
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()

    def _bold_row(self, sheet: str, row_index: int):
        self._format_row(sheet, row_index, bold=True)

    def _header_row(self, sheet: str, row_index: int):
        self._format_row(sheet, row_index, bold=True, bg_color={"red": 0.996, "green": 0.953, "blue": 0.78})

    def _section_row(self, sheet: str, row_index: int):
        self._format_row(sheet, row_index, bold=True, bg_color={"red": 0.965, "green": 0.965, "blue": 0.965})

    def _grand_total_row(self, sheet: str, row_index: int):
        self._format_row(sheet, row_index, bold=True, bg_color={"red": 0.992, "green": 0.9, "blue": 0.54})

    def _format_row(self, sheet: str, row_index: int, bold: bool = False, bg_color: Optional[Dict] = None):
        requests = [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": self._sheet_id(sheet),
                        "startRowIndex": row_index,
                        "endRowIndex": row_index + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": bold},
                            "backgroundColor": bg_color,
                        }
                    },
                    "fields": "userEnteredFormat.textFormat.bold,userEnteredFormat.backgroundColor",
                }
            }
        ]
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id, body={"requests": requests}
        ).execute()

    def _sheet_id(self, sheet: str) -> int:
        spreadsheet = self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        for s in spreadsheet["sheets"]:
            if s["properties"]["title"] == sheet:
                return s["properties"]["sheetId"]
        raise ValueError(f"Sheet {sheet} not found")


def format_shyam_steel_sheet(service_account_json: str, spreadsheet_id: Optional[str] = None) -> Dict[str, Any]:
    """Public helper to format a Shyam Steel Google Sheet."""
    formatter = ShyamSteelSheetsFormatter(service_account_json, spreadsheet_id)
    return formatter.create_or_format()
