"""
DSU course performance report: live data from Google Ads + LeadSquared.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.db.models import Account
from backend.routes.auth import get_current_user_required
from backend.services.dsu_data import fetch_dsu_daily, fetch_dsu_cumulative, DSU_COURSES

router = APIRouter(prefix="/api/reports", tags=["reports"])

# Inception and GST transition dates for DSU
DSU_INCEPTION = "2025-11-28"
DSU_GST_TRANSITION = "2026-06-19"
GST_MULTIPLIER = 1.18


def _fmt_inr(n):
    if n is None:
        return "No Leads"
    return "₹" + str(int(round(n))).replace(",", "_").replace("_", ",")


def _pdf_in(n):
    if n is None:
        return "No Leads"
    return "₹" + str(int(round(n)))


def _pdf_num(n):
    return str(int(n or 0))


def _apply_gst(rows, report_date):
    import datetime

    gst_start = datetime.date.fromisoformat(DSU_GST_TRANSITION)
    report = datetime.date.fromisoformat(report_date)
    include_gst = report >= gst_start
    out = []
    for r in rows:
        spend = r["spend"]
        if include_gst:
            spend = round(spend * GST_MULTIPLIER)
        leads = r["leads"]
        cpl = round(spend / leads) if leads else (r["cpl"] if r["cpl"] is not None else None)
        out.append({"course": r["course"], "leads": leads, "cpl": cpl, "spend": spend, "has_gst": include_gst})
    return out


@router.get("/dsu-performance")
def dsu_performance(
    db: Session = Depends(get_db),
    user=Depends(get_current_user_required),
):
    from datetime import date, timedelta

    account = db.query(Account).filter(Account.name == "DSU").first()
    if not account:
        raise HTTPException(status_code=404, detail="DSU account not found")

    yesterday = (date.today() - timedelta(days=1)).isoformat()

    daily_raw = fetch_dsu_daily(yesterday)
    daily = _apply_gst(daily_raw, yesterday)

    cumulative_raw = fetch_dsu_cumulative(DSU_INCEPTION, yesterday)
    cumulative = [
        {
            "course": r["course"],
            "leads": r["leads"],
            "cpl": r["cpl"],
            "spend": r["spend"],
        }
        for r in cumulative_raw
    ]

    daily_total = {
        "leads": sum(r["leads"] for r in daily),
        "spend": sum(r["spend"] for r in daily),
    }
    daily_total["cpl"] = round(daily_total["spend"] / daily_total["leads"]) if daily_total["leads"] else 0

    cum_total = {
        "leads": sum(r["leads"] for r in cumulative),
        "spend": sum(r["spend"] for r in cumulative),
    }
    cum_total["cpl"] = round(cum_total["spend"] / cum_total["leads"]) if cum_total["leads"] else 0

    return {
        "account": account.to_dict() if account else None,
        "report_date": yesterday,
        "inception_date": DSU_INCEPTION,
        "gst_transition_date": DSU_GST_TRANSITION,
        "gst_note": "Spend values before 19-Jun-2026 are without GST. From 19-Jun-2026 onwards, platform cost is multiplied by 1.18.",
        "daily": {
            "title": f"TABLE 1: {yesterday}",
            "subtitle": "WITHOUT GST (BASE CAMPAIGN METRICS)",
            "rows": daily,
            "total": daily_total,
        },
        "cumulative": {
            "title": f"TABLE 2: {DSU_INCEPTION} - {yesterday}",
            "subtitle": "WITHOUT GST (BASE CAMPAIGN METRICS)",
            "rows": cumulative,
            "total": cum_total,
        },
    }


@router.get("/dsu-performance/pdf")
def dsu_performance_pdf(
    table: str = Query("daily", enum=["daily", "cumulative"]),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_required),
):
    from datetime import date, timedelta
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm

    account = db.query(Account).filter(Account.name == "DSU").first()
    if not account:
        raise HTTPException(status_code=404, detail="DSU account not found")

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    data = dsu_performance(db, user)
    section = data["daily" if table == "daily" else "cumulative"]
    rows = section["rows"]
    total = section["total"]

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "dsuTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        alignment=1,
        textColor=colors.HexColor("#1e3a8a"),
        spaceAfter=4,
    )
    sub_style = ParagraphStyle(
        "dsuSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        alignment=1,
        textColor=colors.HexColor("#4338ca"),
        spaceAfter=6,
    )
    note_style = ParagraphStyle(
        "dsuNote",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#6b7280"),
        spaceAfter=12,
    )

    elements = []
    elements.append(Paragraph("DSU Course Performance Report", title_style))
    elements.append(Paragraph(section["subtitle"], sub_style))
    elements.append(Paragraph(section["title"], sub_style))
    elements.append(Paragraph("MIS", sub_style))
    elements.append(Paragraph(data["gst_note"], note_style))
    elements.append(Spacer(1, 0.3 * cm))

    table_data = [["Course", "Leads", "CPL", "Spend"]]
    for r in rows:
        cpl = _pdf_in(r["cpl"]) if r["leads"] else "No Leads"
        table_data.append([r["course"], _pdf_num(r["leads"]), cpl, _pdf_in(r["spend"])])
    total_cpl = _pdf_in(total["cpl"]) if total["leads"] else "No Leads"
    table_data.append(["TOTAL", _pdf_num(total["leads"]), total_cpl, _pdf_in(total["spend"])])

    t = Table(table_data, colWidths=[9 * cm, 3 * cm, 3.5 * cm, 4 * cm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4338ca")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#c7d2fe")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#a5b4fc")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#eef2ff")]),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
            ]
        )
    )
    elements.append(t)
    elements.append(Spacer(1, 0.5 * cm))
    elements.append(
        Paragraph(
            f"Inception date: {DSU_INCEPTION} | GST transition: {DSU_GST_TRANSITION}",
            note_style,
        )
    )

    doc.build(elements)
    buffer.seek(0)
    filename = f"DSU_{table}_{yesterday}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )