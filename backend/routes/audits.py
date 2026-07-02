"""
Audit and approval queue API routes.
"""
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.db.models import PendingAction, Account, SuppressedSearchTerm, User
from backend.services.auditor import audit_account, audit_all_accounts, review_action, list_pending_actions
from backend.services.scheduler import run_manual_smart_audit
from backend.services.audit_settings import get_audit_settings, set_audit_setting
from backend.services.notifications import dispatch
from backend.services.connectors import get_connector
from backend.routes.auth import get_current_user_required

logger = logging.getLogger("AdOptima")
router = APIRouter(prefix="/api", tags=["audits"])


class ReviewRequest(BaseModel):
    decision: str  # "approve" or "reject"
    reviewer: str = "admin"


class AuditSettingUpdate(BaseModel):
    value: str


class ApplyItem(BaseModel):
    id: int
    type: str
    custom_value: Optional[float] = None


class BulkApplyRequest(BaseModel):
    approved: List[ApplyItem] = Field(default_factory=list)
    rejected: List[int] = Field(default_factory=list)
    dismissed: List[int] = Field(default_factory=list)
    reviewer: str = "admin"


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


def _format_match_type(mt):
    if not mt:
        return "BROAD"
    mt = str(mt).upper().replace("KEYWORDMATCHTYPE.", "")
    mapping = {"1": "BROAD", "2": "PHRASE", "3": "EXACT", "4": "UNKNOWN"}
    if mt in mapping:
        return mapping[mt]
    return mt


@router.get("/audit-runs")
def list_audit_runs(limit: int = 30, db: Session = Depends(get_db)):
    """Return recent smart audit runs (keyword + search term audits)."""
    from backend.db.models import AuditRun
    runs = db.query(AuditRun).order_by(AuditRun.start_time.desc()).limit(limit).all()
    return [r.to_dict() for r in runs]


@router.get("/adpulse/approval-queue/{account_id}/review")
def get_approval_queue_review(account_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """Return all pending recommendations for a single account grouped by type."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if user.role == "user" and account_id not in (user.assigned_account_ids() or []):
        raise HTTPException(status_code=403, detail="Access denied to this account")

    pending = db.query(PendingAction).filter(
        PendingAction.account_id == account_id,
        PendingAction.status == "pending",
    ).order_by(PendingAction.created_at.desc()).all()

    keywords_to_pause = []
    negatives_to_add = []
    budget_changes = []
    campaign_actions = []

    for action in pending:
        nv = action.new_value or {}
        metrics = nv.get("metrics", {}) if isinstance(nv, dict) else {}
        campaign_name = (nv.get("campaign_name") if isinstance(nv, dict) else None) or action.campaign_id or "Unknown"
        campaign_id = action.campaign_id or ""

        if action.action_type in ("SMART_PAUSE_KEYWORD", "PAUSE_KEYWORD"):
            spend = metrics.get("spend", 0) or 0
            clicks = metrics.get("clicks", 0) or 0
            conversions = metrics.get("conversions", 0) or 0
            ctr = metrics.get("ctr", 0) or 0
            cpa = round(spend / conversions, 2) if conversions else None
            keywords_to_pause.append({
                "id": action.id,
                "campaign_name": campaign_name,
                "campaign_id": campaign_id,
                "ad_group_name": nv.get("ad_group_name") if isinstance(nv, dict) else None,
                "ad_group_id": nv.get("ad_group_id") if isinstance(nv, dict) else action.adset_id,
                "keyword_text": action.keyword or "",
                "match_type": _format_match_type(action.match_type),
                "spend_30d": spend,
                "clicks_30d": clicks,
                "conversions_30d": conversions,
                "ctr": ctr,
                "cpa": cpa,
                "reason": action.reason or "",
                "criterion_id": nv.get("criterion_id") if isinstance(nv, dict) else None,
            })

        elif action.action_type in ("SMART_ADD_NEGATIVE_KEYWORD", "ADD_NEGATIVE_KEYWORD"):
            spend = metrics.get("spend", 0) or 0
            clicks = metrics.get("clicks", 0) or 0
            conversions = metrics.get("conversions", 0) or 0
            negatives_to_add.append({
                "id": action.id,
                "campaign_name": campaign_name,
                "campaign_id": campaign_id,
                "search_term": action.keyword or "",
                "clicks": clicks,
                "spend": spend,
                "conversions": conversions,
                "level": nv.get("level") if isinstance(nv, dict) else "campaign",
                "reason": action.reason or "",
                "match_type": _format_match_type(action.match_type),
            })

        elif action.action_type in ("PAUSE_OR_REDUCE_BUDGET",):
            suggested = nv.get("suggested_budget") if isinstance(nv, dict) else None
            budget_changes.append({
                "id": action.id,
                "campaign_name": campaign_name,
                "campaign_id": campaign_id,
                "current_budget": action.account.budget if action.account else 0,
                "suggested_budget": suggested,
                "spend_30d": metrics.get("spend", 0) or 0,
                "clicks_30d": metrics.get("clicks", 0) or 0,
                "conversions_30d": metrics.get("conversions", 0) or 0,
                "ctr": metrics.get("ctr", 0) or 0,
                "cpa": round(metrics.get("spend", 0) / conversions, 2) if conversions else None,
                "reason": action.reason or "",
            })

        elif action.action_type in ("PAUSE_CAMPAIGN", "ENABLE_CAMPAIGN", "ALERT_PERFORMANCE_ISSUE", "ALERT_SETUP_ISSUE"):
            campaign_actions.append({
                "id": action.id,
                "campaign_name": campaign_name,
                "campaign_id": campaign_id,
                "action": action.action_type.lower().replace("_campaign", ""),
                "spend_30d": metrics.get("spend", 0) or 0,
                "clicks_30d": metrics.get("clicks", 0) or 0,
                "conversions_30d": metrics.get("conversions", 0) or 0,
                "ctr": metrics.get("ctr", 0) or 0,
                "cpa": round(metrics.get("spend", 0) / conversions, 2) if conversions else None,
                "reason": action.reason or "",
            })

    # Default audit date = latest action created_at, else today
    audit_dt = pending[0].created_at if pending else datetime.utcnow()
    return {
        "account_id": account_id,
        "account_name": account.name,
        "audit_date": audit_dt.strftime("%d %b %Y, %I:%M %p") if audit_dt else None,
        "keywords_to_pause": keywords_to_pause,
        "negatives_to_add": negatives_to_add,
        "budget_changes": budget_changes,
        "campaign_actions": campaign_actions,
    }


@router.post("/adpulse/approval-queue/apply")
def apply_approval_queue_actions(req: BulkApplyRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """Process approved/rejected/dismissed recommendations in bulk."""
    results = []
    reviewer = req.reviewer or (user.email or user.role or "admin")
    now = datetime.utcnow()
    suppression_days = 30
    try:
        from backend.services.audit_settings import get_int_setting
        suppression_days = get_int_setting("smart_audit_rejection_suppression_days", db) or 30
    except Exception:
        pass

    approved_ids = {item.id for item in req.approved}
    approved_items = {item.id: item for item in req.approved}

    # Process approved items one-by-one
    for item in req.approved:
        action = db.query(PendingAction).filter(PendingAction.id == item.id).first()
        if not action:
            results.append({"id": item.id, "status": "failed", "message": "Action not found"})
            continue
        if action.status != "pending":
            results.append({"id": item.id, "status": "skipped", "message": f"Already {action.status}"})
            continue

        account = db.query(Account).filter(Account.id == action.account_id).first()
        if not account:
            results.append({"id": item.id, "status": "failed", "message": "Account not found"})
            continue

        result = {"success": False, "error": "Unknown action type"}
        try:
            if action.action_type in ("SMART_PAUSE_KEYWORD", "PAUSE_KEYWORD") and action.platform == "google" and account.google_is_live:
                connector = get_connector(account, platform="google")
                if connector and connector.is_valid:
                    nv = action.new_value or {}
                    result = connector.pause_keyword(
                        nv.get("ad_group_id") or action.adset_id or "",
                        nv.get("criterion_id") or "",
                    )
                else:
                    result = {"success": False, "error": "Live Google connector not valid"}

            elif action.action_type in ("SMART_ADD_NEGATIVE_KEYWORD", "ADD_NEGATIVE_KEYWORD") and action.platform == "google" and account.google_is_live:
                connector = get_connector(account, platform="google")
                if connector and connector.is_valid:
                    result = connector.apply_negative_keyword(
                        action.campaign_id or "",
                        action.keyword or "",
                        action.match_type or "EXACT",
                    )
                else:
                    result = {"success": False, "error": "Live Google connector not valid"}

            elif action.action_type in ("PAUSE_OR_REDUCE_BUDGET",) and action.platform == "google":
                # For budget changes, use custom_value if provided; otherwise fall back to suggested
                nv = action.new_value or {}
                new_budget = item.custom_value if item.custom_value is not None else nv.get("suggested_budget")
                if new_budget is None:
                    result = {"success": False, "error": "No budget value provided"}
                elif account.google_is_live:
                    connector = get_connector(account, platform="google")
                    if connector and connector.is_valid:
                        # update_campaign_budget currently raises NotImplementedError; use campaign budget mutation via google_ads
                        from backend.services.google_ads import GoogleAdsApiClient
                        from backend.services.config import load_config
                        config = load_config()
                        safe_mode = config.get("safe_mode", True)
                        if safe_mode:
                            result = {"success": False, "error": "Safe mode is enabled. Disable safe mode to apply budget changes."}
                        else:
                            try:
                                client_cfg = {
                                    "developer_token": account.google_developer_token or (connector._parse_credentials() or {}).get("developer_token", ""),
                                    "client_id": account.google_client_id or (connector._parse_credentials() or {}).get("client_id", ""),
                                    "client_secret": (connector._parse_credentials() or {}).get("client_secret", ""),
                                    "refresh_token": (connector._parse_credentials() or {}).get("refresh_token", ""),
                                    "customer_id": account.google_external_id or account.external_id or "",
                                    "safe_mode": False,
                                }
                                gclient = GoogleAdsApiClient(client_cfg)
                                result = gclient.mutate_campaign_budget(action.campaign_id or "", float(new_budget))
                            except Exception as e:
                                result = {"success": False, "error": str(e)}
                    else:
                        result = {"success": False, "error": "Live Google connector not valid"}
                else:
                    result = {"success": False, "error": "Account is not live; cannot apply action"}

            elif action.action_type in ("PAUSE_CAMPAIGN", "ENABLE_CAMPAIGN"):
                result = {"success": False, "error": "Campaign pause/enable via API not yet implemented"}

            else:
                result = {"success": False, "error": "Action type requires manual implementation"}

        except Exception as e:
            result = {"success": False, "error": str(e)}

        if result.get("success"):
            action.status = "applied"
            action.applied_at = now
            action.error_message = None
            action.reviewed_by = reviewer
            action.reviewed_at = now
            results.append({"id": item.id, "status": "applied", "message": result.get("message", "Applied")})
        else:
            action.status = "failed"
            action.error_message = result.get("error", "Unknown error")
            action.reviewed_by = reviewer
            action.reviewed_at = now
            results.append({"id": item.id, "status": "failed", "message": result.get("error", "Unknown error")})

    # Rejected items: set rejected + suppress search terms for 30 days
    for rid in req.rejected:
        action = db.query(PendingAction).filter(PendingAction.id == rid).first()
        if action and action.status == "pending":
            action.status = "rejected"
            action.reviewed_by = reviewer
            action.reviewed_at = now
            if action.action_type in ("SMART_ADD_NEGATIVE_KEYWORD", "ADD_NEGATIVE_KEYWORD"):
                suppressed_until = date.today() + timedelta(days=suppression_days)
                existing = db.query(SuppressedSearchTerm).filter(
                    SuppressedSearchTerm.account_id == action.account_id,
                    SuppressedSearchTerm.campaign_id == (action.campaign_id or ""),
                    SuppressedSearchTerm.search_term == (action.keyword or ""),
                ).first()
                if existing:
                    existing.suppressed_until = suppressed_until
                    existing.rejected_by = reviewer
                else:
                    db.add(SuppressedSearchTerm(
                        account_id=action.account_id,
                        campaign_id=action.campaign_id or "",
                        search_term=action.keyword or "",
                        suppressed_until=suppressed_until,
                        rejected_by=reviewer,
                    ))

    # Dismissed items: mark as dismissed (will be re-evaluated next audit)
    for did in req.dismissed:
        action = db.query(PendingAction).filter(PendingAction.id == did).first()
        if action and action.status == "pending":
            action.status = "dismissed"
            action.reviewed_by = reviewer
            action.reviewed_at = now

    db.commit()

    return {
        "results": results,
        "rejected_count": len(req.rejected),
        "dismissed_count": len(req.dismissed),
        "applied_count": sum(1 for r in results if r["status"] == "applied"),
        "failed_count": sum(1 for r in results if r["status"] == "failed"),
    }
