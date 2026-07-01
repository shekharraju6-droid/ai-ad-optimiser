"""
Audit and approval queue API routes.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.db.models import PendingAction
from backend.services.auditor import audit_account, audit_all_accounts, review_action, list_pending_actions
from backend.services.scheduler import run_manual_smart_audit
from backend.services.audit_settings import get_audit_settings, set_audit_setting
from backend.services.notifications import dispatch

logger = logging.getLogger("AdOptima")
router = APIRouter(prefix="/api", tags=["audits"])


class ReviewRequest(BaseModel):
    decision: str  # "approve" or "reject"
    reviewer: str = "admin"


class AuditSettingUpdate(BaseModel):
    value: str


@router.get("/audit-settings")
def list_audit_settings():
    return get_audit_settings()


@router.put("/audit-settings/{key}")
def update_audit_setting(key: str, req: AuditSettingUpdate):
    try:
        return set_audit_setting(key, req.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/accounts/{account_id}/smart-audit")
def run_smart_audit_for_account(account_id: int, db: Session = Depends(get_db)):
    """Run keyword + search term audit for a single account on demand."""
    result = run_manual_smart_audit(account_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    total_actions = (
        result.get("keyword_audit", {}).get("actions_generated", 0)
        + result.get("search_term_audit", {}).get("actions_generated", 0)
    )
    if total_actions > 0:
        dispatch(
            "audit_complete",
            f"Smart audit complete for account {account_id}",
            f"{total_actions} keyword/search-term actions generated.",
            db,
        )
    return result


@router.post("/accounts/{account_id}/audit")
def run_account_audit(account_id: int, start_date: Optional[str] = None, end_date: Optional[str] = None, platform: Optional[str] = None, db: Session = Depends(get_db)):
    result = audit_account(account_id, start_date=start_date, end_date=end_date, platform=platform)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    if result.get("actions_generated", 0) > 0:
        dispatch(
            "audit_complete",
            f"Audit complete: {result['account_name']} ({result.get('platform')})",
            f"{result['actions_generated']} optimization actions generated for {result['account_name']}.",
            db,
        )
    return result


@router.post("/audit-all")
def run_all_audits(start_date: Optional[str] = None, end_date: Optional[str] = None, db: Session = Depends(get_db)):
    result = audit_all_accounts(start_date=start_date, end_date=end_date)
    if result.get("total_actions_generated", 0) > 0:
        dispatch(
            "audit_complete",
            "Global audit complete",
            f"{result['total_actions_generated']} optimization actions generated across {result['accounts_audited']} accounts.",
            db,
        )
    return result


@router.post("/pending-actions/clear-pending")
def clear_pending_actions(req: ReviewRequest, db: Session = Depends(get_db)):
    """Delete all pending actions (auto-generated recommendations only)."""
    count = db.query(PendingAction).filter(PendingAction.status == "pending").delete(synchronize_session=False)
    db.commit()
    logger.info(f"Cleared {count} pending actions by {req.reviewer}")
    return {"cleared": count}


@router.get("/pending-actions")
def get_pending_actions(db: Session = Depends(get_db)):
    actions = list_pending_actions(db)
    return [a.to_dict() for a in actions]


@router.post("/pending-actions/{action_id}/review")
def review_pending_action(action_id: int, req: ReviewRequest, db: Session = Depends(get_db)):
    result = review_action(action_id, req.decision, req.reviewer)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    dispatch(
        "action_reviewed",
        f"Action #{result['id']} {result['status']} by {req.reviewer}",
        f"{result['action_type']} for {result['account_name']} - keyword/campaign: {result.get('keyword') or result.get('campaign_id') or result.get('adset_id') or 'n/a'}",
        db,
    )
    return result


@router.get("/accounts/{account_id}/campaigns")
def get_account_campaigns(account_id: int, platform: Optional[str] = None, db: Session = Depends(get_db)):
    """Placeholder for fetching campaigns from real connector."""
    from backend.db.models import Account
    from backend.services.connectors import get_connector
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    target_platform = platform
    if not target_platform:
        if account.account_type == AccountType.GOOGLE:
            target_platform = "google"
        elif account.account_type == AccountType.META:
            target_platform = "meta"
        elif account.has_google:
            target_platform = "google"
        elif account.has_meta:
            target_platform = "meta"

    platform_live = account.google_is_live if target_platform == "google" else account.meta_is_live
    if platform_live:
        connector = get_connector(account, platform=target_platform)
        if connector and connector.is_valid:
            return connector.fetch_campaigns()
    return []


@router.get("/audit-runs")
def list_audit_runs(limit: int = 30, db: Session = Depends(get_db)):
    """Return recent smart audit runs (keyword + search term audits)."""
    from backend.db.models import AuditRun
    runs = db.query(AuditRun).order_by(AuditRun.start_time.desc()).limit(limit).all()
    return [r.to_dict() for r in runs]
