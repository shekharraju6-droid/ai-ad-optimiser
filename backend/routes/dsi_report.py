"""
DSI course performance report: live data from Google Ads + LeadSquared.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.db.models import Account, DsiBudgetEntry
from backend.routes.auth import get_current_user_required
from backend.services.dsi_data import (
    fetch_dsi_daily_range,
    fetch_dsi_cumulative_range,
    fetch_dsi_lead_pivot,
    fetch_dsi_application_mis,
    fetch_dsi_budget_mis,
    DSI_INCEPTION,
    DSI_GST_TRANSITION,
)
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/dsi-performance")
def dsi_performance(
    t1_start: str = Query(None, description="Table 1 start date (YYYY-MM-DD)"),
    t1_end: str = Query(None, description="Table 1 end date (YYYY-MM-DD)"),
    t2_start: str = Query(None, description="Table 2 start date (YYYY-MM-DD)"),
    t2_end: str = Query(None, description="Table 2 end date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_required),
):
    """DSI Table 1 & 2: Daily and cumulative course performance."""
    from datetime import date, timedelta

    account = db.query(Account).filter(Account.name == "DSI").first()
    if not account:
        raise HTTPException(status_code=404, detail="DSI account not found")

    yesterday = (date.today() - timedelta(days=1)).isoformat()

    t1_start_date = t1_start or yesterday
    t1_end_date = t1_end or yesterday
    t2_start_date = t2_start or DSI_INCEPTION
    t2_end_date = t2_end or yesterday

    daily_rows = fetch_dsi_daily_range(t1_start_date, t1_end_date)
    cumulative_rows = fetch_dsi_cumulative_range(t2_start_date, t2_end_date)

    def build_total(rows):
        total_leads = sum(r["leads"] for r in rows)
        total_spend = sum(r["spend"] for r in rows)
        total_cpl = round(total_spend / total_leads) if total_leads else 0
        return {"leads": total_leads, "spend": total_spend, "cpl": total_cpl}

    daily_total = build_total(daily_rows)
    cum_total = build_total(cumulative_rows)

    return {
        "account": account.to_dict() if account else None,
        "t1_start": t1_start_date,
        "t1_end": t1_end_date,
        "t2_start": t2_start_date,
        "t2_end": t2_end_date,
        "inception_date": DSI_INCEPTION,
        "gst_transition_date": DSI_GST_TRANSITION,
        "gst_note": "Spend values before 19-Jun-2026 are without GST. From 19-Jun-2026 onwards, platform cost is multiplied by 1.18.",
        "daily": {
            "title": f"TABLE 1: {t1_start_date}" + (f" to {t1_end_date}" if t1_start_date != t1_end_date else ""),
            "subtitle": "WITHOUT GST (BASE CAMPAIGN METRICS)" if t1_end_date < DSI_GST_TRANSITION else "WITH GST (18% APPLIED)",
            "rows": daily_rows,
            "total": daily_total,
        },
        "cumulative": {
            "title": f"TABLE 2: {t2_start_date} to {t2_end_date}",
            "subtitle": "WITHOUT GST (BASE CAMPAIGN METRICS)" if t2_end_date < DSI_GST_TRANSITION else "WITH GST (18% APPLIED)",
            "rows": cumulative_rows,
            "total": cum_total,
        },
    }


@router.get("/dsi/lead-pivot")
def dsi_lead_pivot(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_required),
):
    """DSI Table 3: Lead attribution pivot (Course × Student Stage)."""
    return fetch_dsi_lead_pivot(start_date, end_date)


@router.get("/dsi/application-mis")
def dsi_application_mis(
    start_date: str = Query(None, description="Start date (default: inception)"),
    end_date: str = Query(None, description="End date (default: yesterday)"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_required),
):
    """DSI Table 4: Application Submitted and CPA by Department."""
    from datetime import date, timedelta
    s = start_date or DSI_INCEPTION
    e = end_date or (date.today() - timedelta(days=1)).isoformat()
    return fetch_dsi_application_mis(s, e)


@router.get("/dsi/budget-mis")
def dsi_budget_mis(
    start_date: str = Query(None, description="Start date (default: inception)"),
    end_date: str = Query(None, description="End date (default: yesterday)"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_required),
):
    """DSI Table 5: Budget MIS by Department."""
    from datetime import date, timedelta
    s = start_date or DSI_INCEPTION
    e = end_date or (date.today() - timedelta(days=1)).isoformat()
    return fetch_dsi_budget_mis(s, e, db_session=db)


# --- Budget entry CRUD for DSI Table 5 ---

class DsiBudgetEntryCreate(BaseModel):
    date: str
    amount: float
    invoice: Optional[str] = ""
    section: Optional[str] = ""


class DsiBudgetEntryUpdate(BaseModel):
    date: Optional[str] = None
    amount: Optional[float] = None
    invoice: Optional[str] = None
    section: Optional[str] = None


@router.get("/dsi/budget-entries")
def list_dsi_budget_entries(
    db: Session = Depends(get_db),
    user=Depends(get_current_user_required),
):
    """List all DSI budget entries."""
    entries = db.query(DsiBudgetEntry).order_by(DsiBudgetEntry.entry_date).all()
    return [e.to_dict() for e in entries]


@router.post("/dsi/budget-entries")
def create_dsi_budget_entry(
    entry: DsiBudgetEntryCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_required),
):
    """Create a new DSI budget entry."""
    new_entry = DsiBudgetEntry(
        entry_date=entry.date,
        amount=entry.amount,
        invoice=entry.invoice or "",
        section=entry.section or "",
    )
    db.add(new_entry)
    db.commit()
    db.refresh(new_entry)
    return new_entry.to_dict()


@router.put("/dsi/budget-entries/{entry_id}")
def update_dsi_budget_entry(
    entry_id: int,
    entry: DsiBudgetEntryUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_required),
):
    """Update a DSI budget entry."""
    existing = db.query(DsiBudgetEntry).filter(DsiBudgetEntry.id == entry_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Budget entry not found")
    if entry.date is not None:
        existing.entry_date = entry.date
    if entry.amount is not None:
        existing.amount = entry.amount
    if entry.invoice is not None:
        existing.invoice = entry.invoice
    if entry.section is not None:
        existing.section = entry.section
    db.commit()
    db.refresh(existing)
    return existing.to_dict()


@router.delete("/dsi/budget-entries/{entry_id}")
def delete_dsi_budget_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_required),
):
    """Delete a DSI budget entry."""
    existing = db.query(DsiBudgetEntry).filter(DsiBudgetEntry.id == entry_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Budget entry not found")
    db.delete(existing)
    db.commit()
    return {"deleted": True, "id": entry_id}