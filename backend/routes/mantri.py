"""
Mantri reporting endpoints.

Currently serves sample/mock data. When Meta Account ID and Salesforce
credentials are configured, real API calls can be wired into the same
endpoint structure without changing the UI.
"""
import io
import logging
from datetime import date, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.routes.auth import get_current_user
from backend.services.config import load_config, save_config

logger = logging.getLogger("AdOptima")

router = APIRouter(prefix="/api", tags=["mantri"])


# ---------- Config models ----------

class MantriConfigModel(BaseModel):
    meta_account_id: str = ""
    salesforce_url: str = ""
    salesforce_client_id: str = ""
    salesforce_client_secret: str = ""
    salesforce_refresh_token: str = ""


_CONFIG_KEYS = {
    "meta_account_id": "mantri_meta_account_id",
    "salesforce_url": "mantri_salesforce_url",
    "salesforce_client_id": "mantri_salesforce_client_id",
    "salesforce_client_secret": "mantri_salesforce_client_secret",
    "salesforce_refresh_token": "mantri_salesforce_refresh_token",
}


# ---------- Helpers ----------

def _today() -> date:
    return date.today()


def _last_3_days() -> List[date]:
    today = _today()
    return [today - timedelta(days=2), today - timedelta(days=1), today]


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) > 4:
        return "●●●●●●●●" + value[-4:]
    return "●●●●●●●●"


def _mantri_config() -> Dict[str, Any]:
    cfg = load_config()
    return {
        "meta_account_id": cfg.get("mantri_meta_account_id", ""),
        "salesforce_url": cfg.get("mantri_salesforce_url", ""),
        "salesforce_client_id": cfg.get("mantri_salesforce_client_id", ""),
        "salesforce_client_secret": _mask(cfg.get("mantri_salesforce_client_secret", "")),
        "salesforce_refresh_token": _mask(cfg.get("mantri_salesforce_refresh_token", "")),
        "configured": bool(
            cfg.get("mantri_meta_account_id")
            and cfg.get("mantri_salesforce_url")
            and cfg.get("mantri_salesforce_client_id")
            and cfg.get("mantri_salesforce_client_secret")
            and cfg.get("mantri_salesforce_refresh_token")
        ),
    }


# ---------- Mock data generators ----------

_PLATFORMS = ["Meta", "Google"]
_PROJECTS = ["DSU", "DSI", "Other"]

# Lead dispositions (vertical rows) as specified by the client
_DISPOSITIONS = [
    "Booked",
    "Closed Lost",
    "Interested",
    "New",
    "Not Interested",
    "Post Site Visit Follow-Up",
    "Pre Sales Follow Up",
    "Qualified",
    "Sales Follow up",
    "Site Visit Schedule",
    "SV Completed",
]


def _mock_lead_status_by_platform() -> List[Dict[str, Any]]:
    """Table 1: Lead Status by Platform with counts + column percentages."""
    rows = []
    platform_totals = {p: 0 for p in _PLATFORMS}
    for d in _DISPOSITIONS:
        row = {"lead_status": d}
        row_total = 0
        for platform in _PLATFORMS:
            value = 8 + (hash(platform + d) % 42)
            row[f"{platform.lower()}_count"] = value
            platform_totals[platform] += value
            row_total += value
        row["overall_count"] = row_total
        rows.append(row)

    # Calculate percentages per column
    ordered_rows = []
    for row in rows:
        ordered = {"lead_status": row["lead_status"]}
        for platform in _PLATFORMS:
            total = platform_totals[platform]
            count_key = f"{platform.lower()}_count"
            pct_key = f"{platform.lower()}_pct"
            count = row[count_key]
            ordered[count_key] = count
            ordered[pct_key] = round((count / total * 100) if total else 0, 1)
        overall_total = sum(platform_totals.values())
        ordered["overall_count"] = row["overall_count"]
        ordered["overall_pct"] = round((row["overall_count"] / overall_total * 100) if overall_total else 0, 1)
        ordered_rows.append(ordered)

    # Grand Total row (counts only, percentages left empty)
    total_row = {"lead_status": "Grand Total - Leads"}
    for platform in _PLATFORMS:
        total_row[f"{platform.lower()}_count"] = platform_totals[platform]
        total_row[f"{platform.lower()}_pct"] = ""
    total_row["overall_count"] = sum(platform_totals.values())
    total_row["overall_pct"] = ""
    ordered_rows.append(total_row)
    return ordered_rows


def _mock_platform_spend_by_project() -> List[Dict[str, Any]]:
    rows = []
    for platform in _PLATFORMS:
        for project in _PROJECTS:
            spend = 25000 + (hash(platform + project) % 50000)
            leads = 50 + (hash(platform + project + "leads") % 150)
            clicks = 300 + (hash(platform + project + "clicks") % 700)
            impressions = 3000 + (hash(platform + project + "impressions") % 12000)
            ctr = round(clicks / impressions * 100, 2)
            cpl = round(spend / leads, 2) if leads else 0
            rows.append({
                "platform": platform,
                "project": project,
                "spend": spend,
                "leads": leads,
                "clicks": clicks,
                "impressions": impressions,
                "ctr": ctr,
                "cpl": cpl,
            })
    return rows


def _mock_daily_breakdown(platform_filter: str = "all") -> List[Dict[str, Any]]:
    days = _last_3_days()
    rows = []
    for day in days:
        for platform in (_PLATFORMS if platform_filter == "all" else [platform_filter]):
            for project in _PROJECTS:
                seed = f"{day.isoformat()}-{platform}-{project}"
                spend = 800 + (hash(seed + "spend") % 4500)
                leads = 5 + (hash(seed + "leads") % 35)
                clicks = 40 + (hash(seed + "clicks") % 160)
                impressions = 400 + (hash(seed + "impressions") % 2600)
                ctr = round(clicks / impressions * 100, 2)
                cpl = round(spend / leads, 2) if leads else 0
                rows.append({
                    "date": day.isoformat(),
                    "display_date": day.strftime("%d-%b-%Y"),
                    "platform": platform,
                    "project": project,
                    "spend": spend,
                    "leads": leads,
                    "clicks": clicks,
                    "impressions": impressions,
                    "ctr": ctr,
                    "cpl": cpl,
                })
    return rows


# ---------- Config endpoints ----------

@router.get("/mantri/config")
def get_mantri_config(current_user=Depends(get_current_user)):
    return _mantri_config()


@router.post("/mantri/config")
def save_mantri_config(payload: MantriConfigModel, current_user=Depends(get_current_user)):
    cfg = load_config()
    updates = {
        _CONFIG_KEYS["meta_account_id"]: payload.meta_account_id.strip(),
        _CONFIG_KEYS["salesforce_url"]: payload.salesforce_url.strip(),
        _CONFIG_KEYS["salesforce_client_id"]: payload.salesforce_client_id.strip(),
    }

    # Preserve masked secrets if the UI sends masked placeholders
    for ui_key in ("salesforce_client_secret", "salesforce_refresh_token"):
        val = getattr(payload, ui_key) or ""
        cfg_key = _CONFIG_KEYS[ui_key]
        if "●●●●" in val:
            updates[cfg_key] = cfg.get(cfg_key, "")
        else:
            updates[cfg_key] = val.strip()

    full = cfg.copy()
    full.update(updates)
    save_config(full)
    return {"status": "success", "config": _mantri_config()}


# ---------- Report endpoints ----------

@router.get("/mantri/reports/lead-status-by-platform")
def lead_status_by_platform(current_user=Depends(get_current_user)):
    return {
        "title": "Report 1: Lead Status by Platform",
        "generated_at": _today().isoformat(),
        "configured": _mantri_config()["configured"],
        "rows": _mock_lead_status_by_platform(),
    }


@router.get("/mantri/reports/platform-spend-by-project")
def platform_spend_by_project(current_user=Depends(get_current_user)):
    return {
        "title": "Report 2: Platform Spend by Project",
        "generated_at": _today().isoformat(),
        "configured": _mantri_config()["configured"],
        "rows": _mock_platform_spend_by_project(),
    }


@router.get("/mantri/reports/daily-meta")
def daily_meta(current_user=Depends(get_current_user)):
    return {
        "title": "Report 3: Daily Meta Report (Last 3 Days)",
        "generated_at": _today().isoformat(),
        "configured": _mantri_config()["configured"],
        "rows": _mock_daily_breakdown("Meta"),
    }


@router.get("/mantri/reports/daily-google")
def daily_google(current_user=Depends(get_current_user)):
    return {
        "title": "Report 4: Daily Google Report (Last 3 Days)",
        "generated_at": _today().isoformat(),
        "configured": _mantri_config()["configured"],
        "rows": _mock_daily_breakdown("Google"),
    }


@router.get("/mantri/reports/daily-combined")
def daily_combined(current_user=Depends(get_current_user)):
    return {
        "title": "Report 5: Daily Combined Platform Report (Last 3 Days)",
        "generated_at": _today().isoformat(),
        "configured": _mantri_config()["configured"],
        "rows": _mock_daily_breakdown("all"),
    }


# ---------- Excel export ----------

try:
    import pandas as pd
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    _HAS_OPENPYXL = True
except Exception:
    _HAS_OPENPYXL = False


@router.get("/mantri/reports/export-excel")
def export_excel(current_user=Depends(get_current_user)):
    if not _HAS_OPENPYXL:
        raise HTTPException(status_code=500, detail="openpyxl is not installed")

    from openpyxl import Workbook

    wb = Workbook()
    # Remove default sheet and add report sheets
    wb.remove(wb.active)

    reports = [
        ("Lead Status by Platform", _mock_lead_status_by_platform()),
        ("Platform Spend by Project", _mock_platform_spend_by_project()),
        ("Daily Meta", _mock_daily_breakdown("Meta")),
        ("Daily Google", _mock_daily_breakdown("Google")),
        ("Daily Combined", _mock_daily_breakdown("all")),
    ]

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    for sheet_name, rows in reports:
        ws = wb.create_sheet(title=sheet_name[:31])
        if not rows:
            ws.append(["No data available"])
            continue

        if sheet_name == "Lead Status by Platform":
            # Two-level header + styled grand total row
            red_fill = PatternFill(start_color="991B1B", end_color="991B1B", fill_type="solid")
            red_font = Font(bold=True, color="FFFFFF")
            center = Alignment(horizontal="center", vertical="center")

            # Top header row
            ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=1)
            ws.cell(row=1, column=1, value="Mantri")
            ws.cell(row=1, column=1).fill = red_fill
            ws.cell(row=1, column=1).font = red_font
            ws.cell(row=1, column=1).alignment = center

            ws.merge_cells(start_row=1, start_column=2, end_row=1, end_column=3)
            ws.cell(row=1, column=2, value="Meta")
            ws.cell(row=1, column=2).fill = red_fill
            ws.cell(row=1, column=2).font = red_font
            ws.cell(row=1, column=2).alignment = center

            ws.merge_cells(start_row=1, start_column=4, end_row=1, end_column=5)
            ws.cell(row=1, column=4, value="Google")
            ws.cell(row=1, column=4).fill = red_fill
            ws.cell(row=1, column=4).font = red_font
            ws.cell(row=1, column=4).alignment = center

            ws.merge_cells(start_row=1, start_column=6, end_row=1, end_column=7)
            ws.cell(row=1, column=6, value="Overall")
            ws.cell(row=1, column=6).fill = red_fill
            ws.cell(row=1, column=6).font = red_font
            ws.cell(row=1, column=6).alignment = center

            # Second header row
            second_headers = ["Lead Status", "Count", "Percentage", "Count", "Percentage", "Count", "Percentage"]
            for col, h in enumerate(second_headers, start=1):
                cell = ws.cell(row=2, column=col, value=h)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = center
                cell.border = thin_border

            for row in rows:
                ws.append([row.get(h) for h in list(rows[0].keys())])

            # Style grand total row
            last_row = ws.max_row
            if rows[-1].get("lead_status", "").lower().startswith("grand total"):
                for col in range(1, 8):
                    cell = ws.cell(row=last_row, column=col)
                    cell.fill = red_fill
                    cell.font = red_font
                    cell.alignment = center if col == 1 else Alignment(horizontal="right")
        else:
            headers = list(rows[0].keys())
            ws.append(headers)
            for cell in ws[1]:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_align
                cell.border = thin_border
            for row in rows:
                ws.append([row.get(h) for h in headers])

        for column in ws.columns:
            max_length = 0
            col_letter = column[0].column_letter
            for cell in column:
                cell.border = thin_border
                try:
                    val = str(cell.value) if cell.value is not None else ""
                    if len(val) > max_length:
                        max_length = len(val)
                except Exception:
                    pass
            adjusted_width = min(max(max_length + 2, 10), 40)
            ws.column_dimensions[col_letter].width = adjusted_width

        # Freeze header row
        ws.freeze_panes = "A2"

    filename = f"Mantri_Reports_{_today().isoformat()}.xlsx"
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
