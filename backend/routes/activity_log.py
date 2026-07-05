"""
Activity history log API endpoints.
"""
import csv
import io
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from backend.db.database import get_db
from backend.db.models import ActivityLog, Account, User
from backend.routes.auth import get_current_user_required

router = APIRouter(prefix="/api", tags=["activity_log"])


def _parse_iso_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


@router.get("/activity-log")
def list_activity_log(
    module: Optional[str] = None,
    account_id: Optional[int] = None,
    user_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Return paginated activity log entries with optional filters.

    Only admin and superadmin can access this endpoint.
    """
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    q = db.query(ActivityLog)
    if module and module.lower() != "all":
        q = q.filter(ActivityLog.module.ilike(module))
    if account_id:
        q = q.filter(ActivityLog.account_id == account_id)
    if user_id:
        q = q.filter(ActivityLog.user_id == user_id)
    start_dt = _parse_iso_date(start_date)
    end_dt = _parse_iso_date(end_date)
    if start_dt and end_dt:
        q = q.filter(and_(ActivityLog.timestamp >= start_dt, ActivityLog.timestamp <= end_dt))
    elif start_dt:
        q = q.filter(ActivityLog.timestamp >= start_dt)
    elif end_dt:
        q = q.filter(ActivityLog.timestamp <= end_dt)

    total = q.count()
    items = q.order_by(desc(ActivityLog.timestamp)).offset(offset).limit(limit).all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [i.to_dict() for i in items],
    }


@router.get("/activity-log/export")
def export_activity_log(
    module: Optional[str] = None,
    account_id: Optional[int] = None,
    user_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Export filtered activity log as CSV. Admin/superadmin only."""
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    q = db.query(ActivityLog)
    if module and module.lower() != "all":
        q = q.filter(ActivityLog.module.ilike(module))
    if account_id:
        q = q.filter(ActivityLog.account_id == account_id)
    if user_id:
        q = q.filter(ActivityLog.user_id == user_id)
    start_dt = _parse_iso_date(start_date)
    end_dt = _parse_iso_date(end_date)
    if start_dt and end_dt:
        q = q.filter(and_(ActivityLog.timestamp >= start_dt, ActivityLog.timestamp <= end_dt))
    elif start_dt:
        q = q.filter(ActivityLog.timestamp >= start_dt)
    elif end_dt:
        q = q.filter(ActivityLog.timestamp <= end_dt)

    items = q.order_by(desc(ActivityLog.timestamp)).limit(500).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "Module", "Action", "Description", "User", "Client/Brand"])
    for i in items:
        writer.writerow([
            i.timestamp.isoformat() if i.timestamp else "",
            i.module,
            i.action,
            i.description,
            i.user_name or "",
            i.account_name or "",
        ])

    from fastapi.responses import StreamingResponse
    output.seek(0)
    filename = f"activity_log_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/activity-log/accounts")
def activity_log_accounts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    """Distinct accounts referenced in activity log."""
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    rows = db.query(ActivityLog.account_id, ActivityLog.account_name).distinct().all()
    return [
        {"id": r.account_id, "name": r.account_name or ("Account " + str(r.account_id) if r.account_id else "N/A")}
        for r in rows
    ]


@router.get("/activity-log/users")
def activity_log_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    """Distinct users referenced in activity log."""
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    rows = db.query(ActivityLog.user_id, ActivityLog.user_name).distinct().all()
    return [
        {"id": r.user_id, "name": r.user_name or ("User " + str(r.user_id) if r.user_id else "System")}
        for r in rows
    ]
