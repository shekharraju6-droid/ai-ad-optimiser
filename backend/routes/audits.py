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
from backend.db.models import PendingAction, Account, SuppressedSearchTerm, User, CampaignLandingPage
from backend.services.auditor import audit_account, audit_all_accounts, review_action, list_pending_actions
from backend.services.scheduler import run_manual_smart_audit
from backend.services.audit_settings import get_audit_settings, set_audit_setting
from backend.services.notifications import dispatch
from backend.services.connectors import get_connector
from backend.services.landing_page_service import fetch_campaign_landing_pages, crawl_stale_landing_pages, fetch_single_landing_page
from backend.services.activity_log import log_activity
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


class MergedApplyItem(BaseModel):
    """Frontend sends merged item ids + the representative action type."""
    ids: List[int]
    type: str
    custom_value: Optional[float] = None


class BulkApplyRequest(BaseModel):
    approved: List[ApplyItem] = Field(default_factory=list)
    merged_approved: List[MergedApplyItem] = Field(default_factory=list)
    rejected: List[int] = Field(default_factory=list)
    merged_rejected: List[MergedApplyItem] = Field(default_factory=list)
    dismissed: List[int] = Field(default_factory=list)
    merged_dismissed: List[MergedApplyItem] = Field(default_factory=list)
    reviewer: str = "admin"


class RunCampaignAuditRequest(BaseModel):
    campaign_id: Optional[str] = None


@router.get("/audit-settings")
def list_audit_settings():
    return get_audit_settings()


@router.put("/audit-settings/{key}")
def update_audit_setting(key: str, req: AuditSettingUpdate):
    try:
        return set_audit_setting(key, req.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _require_audit_review_access(user: User):
    """Raise 403 if user lacks AI Audit Review access. Admins/superadmins always pass."""
    if user.role in ("admin", "superadmin"):
        return
    if not getattr(user, "access_audit_review", False):
        raise HTTPException(status_code=403, detail="You do not have AI Audit Review access")


@router.post("/accounts/{account_id}/smart-audit")
def run_smart_audit_for_account(account_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """Run keyword + search term audit for a single account on demand."""
    _require_audit_review_access(user)
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



@router.post("/adpulse/accounts/{account_id}/run-audit")
def run_adpulse_audit(account_id: int, req: RunCampaignAuditRequest = None, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """Run a fresh AI audit for a single account or single campaign from the AdPulse review UI.

    Returns keyword + search term audit results. If Gemini quota is exhausted,
    keyword results are still returned and search term audit contains a clear
    warning so the frontend can show partial results.
    """
    _require_audit_review_access(user)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if user.role in ("user", "newuser") and account_id not in (user.assigned_account_ids() or []):
        raise HTTPException(status_code=403, detail="Access denied to this account")

    campaign_id = (req and req.campaign_id) or None
    campaign_name = None
    if campaign_id:
        # Try to fetch campaign name for the log
        try:
            cname_map = _fetch_campaign_name_map(account)
            campaign_name = cname_map.get(str(campaign_id))
        except Exception:
            pass

    result = run_manual_smart_audit(account_id, campaign_id=campaign_id)

    # Normalize result so frontend always gets the expected shape
    keyword_audit = result.get("keyword_audit") or {"actions_generated": 0}
    search_term_audit = result.get("search_term_audit") or {"actions_generated": 0}

    # If the orchestration itself failed, surface keyword/search term errors separately
    if result.get("error"):
        err = result["error"]
        # Try to keep keyword results if they were produced before the failure
        if not keyword_audit.get("error") and keyword_audit.get("actions_generated", 0) == 0:
            keyword_audit["error"] = err
        if not search_term_audit.get("error") and search_term_audit.get("actions_generated", 0) == 0:
            search_term_audit["error"] = err

    # Detect quota/rate-limit errors and reword them as a user-friendly warning
    quota_phrases = ("quota", "rate limit", "rate_limit", "429", "exhausted", "resource exhausted")
    st_error = search_term_audit.get("error") or ""
    if any(p in st_error.lower() for p in quota_phrases):
        search_term_audit["warning"] = "⚠️ Search term analysis skipped — Gemini API quota exhausted. Try again tomorrow or upgrade to paid API."
        search_term_audit["actions_generated"] = search_term_audit.get("actions_generated", 0)

    # Log activity: audit run
    kw_count = keyword_audit.get("actions_generated", 0)
    st_count = search_term_audit.get("actions_generated", 0)
    log_description = f"Ran audit for campaign {campaign_name or campaign_id or 'all campaigns'} on {account.name}"
    if campaign_id and not campaign_name:
        log_description = f"Ran audit for campaign {campaign_id} on {account.name}"
    log_activity(
        module="AdPulse",
        action="Audit Run",
        description=log_description,
        user_id=user.id,
        user_name=user.full_name or user.email,
        account_id=account.id,
        account_name=account.name,
        entity_type="campaign",
        entity_id=campaign_id or "",
        details={
            "keyword_actions": kw_count,
            "search_term_actions": st_count,
            "search_term_warning": search_term_audit.get("warning"),
            "search_term_error": search_term_audit.get("error"),
        },
        db=db,
    )

    # Compute legacy budget/campaign action counts from existing pending actions
    budget_actions = db.query(PendingAction).filter(
        PendingAction.account_id == account_id,
        PendingAction.status == "pending",
        PendingAction.action_type == "PAUSE_OR_REDUCE_BUDGET",
        PendingAction.campaign_status == "ENABLED",
    ).count()
    campaign_actions = db.query(PendingAction).filter(
        PendingAction.account_id == account_id,
        PendingAction.status == "pending",
        PendingAction.action_type.in_(("PAUSE_CAMPAIGN", "ENABLE_CAMPAIGN", "ALERT_SETUP_ISSUE", "ALERT_PERFORMANCE_ISSUE", "ALERT_MISSING_LANDING_PAGE")),
        PendingAction.campaign_status == "ENABLED",
    ).count()

    response = {
        "account_id": account_id,
        "account_name": account.name,
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "keyword_audit": keyword_audit,
        "search_term_audit": search_term_audit,
        "budget_actions_generated": budget_actions,
        "campaign_actions_generated": campaign_actions,
    }

    # Only raise a hard error if keyword audit completely failed and we have nothing to show
    if keyword_audit.get("error") and keyword_audit.get("actions_generated", 0) == 0:
        raise HTTPException(status_code=400, detail=keyword_audit["error"])

    total_actions = kw_count + st_count
    if total_actions > 0:
        dispatch(
            "audit_complete",
            f"AI audit complete for {account.name}",
            f"{total_actions} keyword/search-term actions generated.",
            db,
        )
    return response


@router.post("/accounts/{account_id}/refresh-landing-pages")
def refresh_landing_pages(account_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """Pull landing page URLs from Google Ads and crawl stale pages. Triggered manually from AdPulse."""
    _require_audit_review_access(user)
    result = fetch_campaign_landing_pages(account_id, db=db)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    crawl_result = crawl_stale_landing_pages(account_id, db=db)
    return {"fetch": result, "crawl": crawl_result}


@router.get("/accounts/{account_id}/landing-pages")
def list_landing_pages(account_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """List stored landing pages + crawl status for an account."""
    _require_audit_review_access(user)
    from backend.db.models import CampaignLandingPage
    rows = db.query(CampaignLandingPage).filter(CampaignLandingPage.account_id == account_id).all()
    return [r.to_dict() for r in rows]


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
def clear_pending_actions(req: ReviewRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """Delete all pending actions (auto-generated recommendations only)."""
    _require_audit_review_access(user)
    count = db.query(PendingAction).filter(PendingAction.status == "pending").delete(synchronize_session=False)
    db.commit()
    logger.info(f"Cleared {count} pending actions by {req.reviewer}")
    return {"cleared": count}


@router.get("/pending-actions")
def get_pending_actions(db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    _require_audit_review_access(user)
    actions = list_pending_actions(db)
    return [a.to_dict() for a in actions]


@router.post("/pending-actions/{action_id}/review")
def review_pending_action(action_id: int, req: ReviewRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    _require_audit_review_access(user)
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


def _is_numeric_campaign_name(name: str) -> bool:
    """Return True when the campaign name looks like a bare Google Ads campaign ID (all digits)."""
    if not name:
        return False
    return name.strip().isdigit()


def _display_campaign_name(name: str, campaign_id: str) -> str:
    """Frontend-friendly fallback: show 'Campaign #ID' when name is missing or numeric."""
    if name and not _is_numeric_campaign_name(name):
        return name
    if campaign_id:
        return f"Campaign #{campaign_id}"
    return name or "Unknown"


def _fetch_campaign_name_map(account) -> Dict[str, str]:
    """Fetch campaigns from Google Ads and build campaign_id -> name map. Non-blocking."""
    try:
        connector = get_connector(account, platform="google")
        if not connector or not connector.is_valid:
            return {}
        campaigns = connector.fetch_campaigns()
        return {str(c.get("id") or ""): c.get("name") or "" for c in campaigns if c.get("id")}
    except Exception as e:
        logger.warning(f"Failed to fetch campaign name map for account {getattr(account, 'id', '?')}: {e}")
        return {}


def _parse_inr(value: float) -> str:
    try:
        return f"INR {value:,.0f}"
    except Exception:
        return f"INR {value}"


def _classify_keyword_finding(action: PendingAction) -> Optional[Dict[str, Any]]:
    """Map a keyword PendingAction to a structured finding with category + icon."""
    nv = action.new_value or {}
    if not isinstance(nv, dict):
        nv = {}
    check = nv.get("check", "")
    metrics = nv.get("metrics", {})
    spend = metrics.get("spend", 0) or 0
    clicks = metrics.get("clicks", 0) or 0
    conversions = metrics.get("conversions", 0) or 0

    if check == "non_brand_in_brand_campaign":
        return {
            "category": "Keyword",
            "icon": "🔑",
            "detail": f"Non-brand keyword found in Brand campaign — does not contain any brand term",
            "check": check,
        }
    if check == "non_performing_keyword" or (spend > 0 and conversions == 0):
        return {
            "category": "Spend",
            "icon": "💰",
            "detail": f"Spent {_parse_inr(spend)} with {clicks:,.0f} clicks and {conversions} conversions in 30 days",
            "check": check,
        }
    return {
        "category": "Performance",
        "icon": "📊",
        "detail": action.reason or "Performance issue flagged",
        "check": check,
    }


def _classify_search_term_finding(action: PendingAction) -> Dict[str, Any]:
    """Map a search term PendingAction to a structured finding."""
    nv = action.new_value or {}
    if not isinstance(nv, dict):
        nv = {}
    metrics = nv.get("metrics", {})
    spend = metrics.get("spend", 0) or 0
    clicks = metrics.get("clicks", 0) or 0
    conversions = metrics.get("conversions", 0) or 0
    reason = action.reason or ""
    gemini_reason = nv.get("gemini_reason", "")
    irrelevant_detail = f"Irrelevant search term — {gemini_reason}" if gemini_reason else (
        reason if reason else "Irrelevant search term"
    )
    findings = [
        {
            "category": "Relevance",
            "icon": "🔍",
            "detail": irrelevant_detail,
        }
    ]
    if spend > 0 and conversions == 0:
        findings.append({
            "category": "Spend",
            "icon": "💰",
            "detail": f"Spent {_parse_inr(spend)} with 0 conversions",
        })
    return findings


def _normalize_campaign_status(st):
    """Map legacy numeric campaign statuses to readable strings.

    Google Ads CampaignStatus proto enum:
      UNSPECIFIED=0, UNKNOWN=1, ENABLED=2, PAUSED=3, REMOVED=4
    """
    if st is None:
        return "ENABLED"
    raw = str(st).upper().strip()
    status_map = {
        "0": "UNKNOWN",
        "1": "UNKNOWN",
        "2": "ENABLED",
        "3": "PAUSED",
        "4": "REMOVED",
    }
    return status_map.get(raw, raw)


def _merge_keyword_actions(actions: List[PendingAction], campaign_name_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Group pending keyword pause actions by campaign + keyword_text and merge findings."""
    campaign_name_map = campaign_name_map or {}
    groups: Dict[str, Dict[str, Any]] = {}
    for action in actions:
        if action.action_type not in ("SMART_PAUSE_KEYWORD", "PAUSE_KEYWORD"):
            continue
        nv = action.new_value or {}
        if not isinstance(nv, dict):
            nv = {}
        campaign_id = action.campaign_id or ""
        keyword_text = action.keyword or ""
        key = f"{campaign_id}::{keyword_text}"
        metrics = nv.get("metrics", {})
        spend = metrics.get("spend", 0) or 0
        clicks = metrics.get("clicks", 0) or 0
        conversions = metrics.get("conversions", 0) or 0
        ctr = metrics.get("ctr", 0) or 0
        raw_name = nv.get("campaign_name") or ""
        campaign_name = _display_campaign_name(raw_name or campaign_name_map.get(campaign_id, ""), campaign_id)
        confidence = (getattr(action, "confidence", None) or nv.get("confidence") or "MEDIUM").upper()
        confidence_score = getattr(action, "confidence_score", None)
        if confidence_score is None:
            try:
                confidence_score = int(nv.get("confidence_score"))
            except Exception:
                confidence_score = None

        if key not in groups:
            groups[key] = {
                "keyword_text": keyword_text,
                "campaign_name": campaign_name,
                "campaign_id": campaign_id,
                "ad_group_name": nv.get("ad_group_name"),
                "ad_group_id": nv.get("ad_group_id") or action.adset_id,
                "match_type": _format_match_type(action.match_type),
                "spend_30d": spend,
                "clicks_30d": clicks,
                "conversions_30d": conversions,
                "ctr": ctr,
                "queue_item_ids": [],
                "findings": [],
                "campaign_status": _normalize_campaign_status(action.campaign_status),
                "confidence": confidence,
                "confidence_score": confidence_score,
                "_seen_categories": set(),
            }
        grp = groups[key]
        grp["queue_item_ids"].append(action.id)
        # Aggregate metrics to the highest spend values across merged items
        if spend > grp["spend_30d"]:
            grp["spend_30d"] = spend
            grp["clicks_30d"] = clicks
            grp["conversions_30d"] = conversions
            grp["ctr"] = ctr
            grp["match_type"] = _format_match_type(action.match_type)
            grp["ad_group_name"] = nv.get("ad_group_name") or grp["ad_group_name"]
            grp["ad_group_id"] = nv.get("ad_group_id") or action.adset_id or grp["ad_group_id"]
        # Keep highest confidence score
        if confidence_score is not None and (grp.get("confidence_score") is None or confidence_score > (grp.get("confidence_score") or 0)):
            grp["confidence"] = confidence
            grp["confidence_score"] = confidence_score
        finding = _classify_keyword_finding(action)
        cat = finding["category"]
        if cat not in grp["_seen_categories"]:
            grp["_seen_categories"].add(cat)
            grp["findings"].append(finding)

    result = []
    for grp in groups.values():
        grp.pop("_seen_categories", None)
        result.append(grp)
    return result


def _merge_generic_actions(items: List[Dict[str, Any]], key_fields=("campaign_id",)) -> List[Dict[str, Any]]:
    """Merge duplicate generic recommendations by key fields, collecting ids."""
    groups: Dict[str, Dict[str, Any]] = {}
    for item in items:
        key_parts = [str(item.get(f, "")) for f in key_fields]
        key = "::".join(key_parts)
        if key not in groups:
            grp = dict(item)
            grp["id"] = item.get("id")
            grp["queue_item_ids"] = [item.get("id")]
            grp["findings"] = [{"category": "Campaign", "icon": "⚙️", "detail": item.get("reason", "")}]
            groups[key] = grp
        else:
            grp = groups[key]
            grp["queue_item_ids"].append(item.get("id"))
            if item.get("reason"):
                grp["findings"].append({"category": "Campaign", "icon": "⚙️", "detail": item.get("reason")})
    return list(groups.values())


def _merge_search_term_actions(actions: List[PendingAction], campaign_name_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Group pending negative-keyword actions by campaign + search_term and merge findings."""
    campaign_name_map = campaign_name_map or {}
    groups: Dict[str, Dict[str, Any]] = {}
    for action in actions:
        if action.action_type not in ("SMART_ADD_NEGATIVE_KEYWORD", "ADD_NEGATIVE_KEYWORD"):
            continue
        nv = action.new_value or {}
        if not isinstance(nv, dict):
            nv = {}
        campaign_id = action.campaign_id or ""
        term = action.keyword or ""
        key = f"{campaign_id}::{term}"
        metrics = nv.get("metrics", {})
        spend = metrics.get("spend", 0) or 0
        clicks = metrics.get("clicks", 0) or 0
        conversions = metrics.get("conversions", 0) or 0
        ctr = metrics.get("ctr", 0) or 0
        raw_name = nv.get("campaign_name") or ""
        campaign_name = _display_campaign_name(raw_name or campaign_name_map.get(campaign_id, ""), campaign_id)
        confidence = (getattr(action, "confidence", None) or nv.get("confidence") or "MEDIUM").upper()
        confidence_score = getattr(action, "confidence_score", None)
        if confidence_score is None:
            try:
                confidence_score = int(nv.get("confidence_score"))
            except Exception:
                confidence_score = None

        if key not in groups:
            groups[key] = {
                "search_term": term,
                "campaign_name": campaign_name,
                "campaign_id": campaign_id,
                "level": nv.get("level") or "campaign",
                "match_type": _format_match_type(action.match_type),
                "spend": spend,
                "clicks": clicks,
                "conversions": conversions,
                "ctr": ctr,
                "queue_item_ids": [],
                "findings": [],
                "campaign_status": _normalize_campaign_status(action.campaign_status),
                "confidence": confidence,
                "confidence_score": confidence_score,
                "_seen_categories": set(),
            }
        grp = groups[key]
        grp["queue_item_ids"].append(action.id)
        if spend > grp["spend"]:
            grp["spend"] = spend
            grp["clicks"] = clicks
            grp["conversions"] = conversions
            grp["ctr"] = ctr
        # Keep highest confidence score
        if confidence_score is not None and (grp.get("confidence_score") is None or confidence_score > (grp.get("confidence_score") or 0)):
            grp["confidence"] = confidence
            grp["confidence_score"] = confidence_score
        for finding in _classify_search_term_finding(action):
            cat = finding["category"]
            if cat not in grp["_seen_categories"]:
                grp["_seen_categories"].add(cat)
                grp["findings"].append(finding)

    result = []
    for grp in groups.values():
        grp.pop("_seen_categories", None)
        result.append(grp)
    return result


@router.get("/audit-runs")
def list_audit_runs(limit: int = 30, db: Session = Depends(get_db)):
    """Return recent smart audit runs (keyword + search term audits)."""
    from backend.db.models import AuditRun
    runs = db.query(AuditRun).order_by(AuditRun.start_time.desc()).limit(limit).all()
    return [r.to_dict() for r in runs]


SMART_APPROVE_SETTING_KEYS = {
    "smart_approve_confidence": "high",
    "smart_approve_max_spend": "500",
    "smart_approve_conversions": "zero",
    "smart_approve_auto": "off",
}


@router.get("/smart-approve-settings")
def get_smart_approve_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """Return Smart Approve default settings from app_settings."""
    from backend.db.models import AppSetting
    result = dict(SMART_APPROVE_SETTING_KEYS)
    for key in SMART_APPROVE_SETTING_KEYS:
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row and row.value is not None:
            result[key] = row.value
    return result


class SmartApproveSettingUpdate(BaseModel):
    smart_approve_confidence: Optional[str] = None
    smart_approve_max_spend: Optional[str] = None
    smart_approve_conversions: Optional[str] = None
    smart_approve_auto: Optional[str] = None


@router.put("/smart-approve-settings")
def update_smart_approve_settings(req: SmartApproveSettingUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """Update Smart Approve default settings in app_settings."""
    from backend.db.models import AppSetting
    updates = {}
    if req.smart_approve_confidence is not None:
        updates["smart_approve_confidence"] = req.smart_approve_confidence
    if req.smart_approve_max_spend is not None:
        updates["smart_approve_max_spend"] = req.smart_approve_max_spend
    if req.smart_approve_conversions is not None:
        updates["smart_approve_conversions"] = req.smart_approve_conversions
    if req.smart_approve_auto is not None:
        updates["smart_approve_auto"] = req.smart_approve_auto
    for key, value in updates.items():
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))
    db.commit()
    return {"updated": list(updates.keys())}


def _build_campaign_keyword_context(account, pending_actions, campaign_name_map: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Fetch all keywords for campaigns that have flagged items, return context with flagged status.

    Returns a dict keyed by campaign_id:
    {
      "campaign_id": {
        "campaign_name": "...",
        "keywords": [
          {"text": "...", "match_type": "BROAD", "status": "ENABLED", "spend": 100, "clicks": 5, "conversions": 0, "ctr": 3.2, "flagged": true/false}
        ]
      }
    }
    """
    campaign_name_map = campaign_name_map or {}
    # Collect unique campaign_ids from pending keyword actions
    flagged_campaign_ids = set()
    flagged_keyword_keys = set()  # (campaign_id, keyword_text)
    for action in pending_actions:
        if action.action_type in ("SMART_PAUSE_KEYWORD", "PAUSE_KEYWORD"):
            cid = action.campaign_id or ""
            kw = (action.keyword or "").lower()
            flagged_campaign_ids.add(cid)
            flagged_keyword_keys.add((cid, kw))

    if not flagged_campaign_ids:
        return {}

    # Try to fetch all keywords from Google Ads for those campaigns
    try:
        connector = get_connector(account, platform="google")
        if not connector or not connector.is_valid:
            return {}
        all_keywords = connector.fetch_keywords()
    except Exception as e:
        logger.warning(f"Failed to fetch keyword context: {e}")
        return {}

    context: Dict[str, Any] = {}
    for kw in all_keywords:
        cid = kw.get("campaign_id", "")
        if cid not in flagged_campaign_ids:
            continue
        if cid not in context:
            raw_name = kw.get("campaign_name", "") or campaign_name_map.get(cid, "")
            context[cid] = {
                "campaign_name": _display_campaign_name(raw_name, cid),
                "keywords": [],
            }
        kw_text = (kw.get("text") or "").lower()
        is_flagged = (cid, kw_text) in flagged_keyword_keys
        context[cid]["keywords"].append({
            "text": kw.get("text", ""),
            "match_type": _format_match_type(kw.get("match_type", "")),
            "status": kw.get("status", "ENABLED"),
            "spend": kw.get("spend", 0) or 0,
            "clicks": kw.get("clicks", 0) or 0,
            "conversions": kw.get("conversions", 0) or 0,
            "ctr": kw.get("ctr", 0) or 0,
            "flagged": is_flagged,
        })
    # Sort keywords: flagged first, then by spend descending
    for cid in context:
        context[cid]["keywords"].sort(key=lambda k: (not k["flagged"], -(k["spend"] or 0)))
    return context


def _pending_actions_for_campaign(account_id: int, campaign_id: str, db: Session) -> List[PendingAction]:
    return db.query(PendingAction).filter(
        PendingAction.account_id == account_id,
        PendingAction.campaign_id == campaign_id,
    ).order_by(PendingAction.created_at.desc()).all()


@router.get("/accounts/{account_id}/campaign-audit-summary")
def get_campaign_audit_summary(account_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """Return enabled campaigns with last-audited dates for an account.

    Priority:
      1. DISTINCT campaign_id/campaign_name from pending_actions (instant,
         already audited/known).
      2. Live Google Ads API fetch for enabled campaigns (most accurate).
      3. Stored campaign_landing_pages as final fallback.
    """
    _require_audit_review_access(user)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if user.role in ("user", "newuser") and account_id not in (user.assigned_account_ids() or []):
        raise HTTPException(status_code=403, detail="Access denied to this account")

    enabled_campaigns = []
    seen_ids = set()

    # ---- Option A: pending_actions (instant, no API call) ----
    pending_rows = db.query(
        PendingAction.campaign_id,
        PendingAction.campaign_status,
        PendingAction.created_at,
        PendingAction.new_value,
    ).filter(
        PendingAction.account_id == account_id,
        PendingAction.campaign_id.isnot(None),
    ).order_by(PendingAction.created_at.desc()).all()

    print(f"[campaign-audit-summary] account={account_id} pending_actions_rows={len(pending_rows)}")

    for row in pending_rows:
        cid = str(row.campaign_id or "").strip()
        if not cid or cid in seen_ids:
            continue
        status = _normalize_campaign_status(row.campaign_status)
        if status not in ("ENABLED", "UNKNOWN"):
            continue
        seen_ids.add(cid)
        # Campaign name is stored inside new_value JSON payload
        nv = row.new_value or {}
        campaign_name = nv.get("campaign_name") if isinstance(nv, dict) else None
        enabled_campaigns.append({
            "campaign_id": cid,
            "campaign_name": _display_campaign_name(campaign_name or "", cid),
            "status": "ENABLED",
            "last_audited_at": row.created_at.isoformat() if row.created_at else None,
        })

    print(f"[campaign-audit-summary] account={account_id} after pending_actions: {len(enabled_campaigns)} campaigns")

    # ---- Option B: live Google Ads fetch (fills any missing live campaigns) ----
    if account.has_google and account.google_is_live:
        try:
            connector = get_connector(account, platform="google")
            if connector and connector.is_valid:
                live_campaigns = connector.fetch_campaigns()
                print(f"[campaign-audit-summary] account={account_id} live_fetch_campaigns={len(live_campaigns)}")
                for c in live_campaigns:
                    cid = str(c.get("id") or "").strip()
                    if not cid:
                        continue
                    status = _normalize_campaign_status(c.get("status"))
                    print(f"[campaign-audit-summary] account={account_id} live_campaign cid={cid} status={status}")
                    if status != "ENABLED":
                        continue
                    if cid in seen_ids:
                        # If already from pending_actions, keep name from live if more accurate
                        for item in enabled_campaigns:
                            if item["campaign_id"] == cid and c.get("name"):
                                item["campaign_name"] = c.get("name")
                        continue
                    seen_ids.add(cid)
                    enabled_campaigns.append({
                        "campaign_id": cid,
                        "campaign_name": c.get("name") or f"Campaign #{cid}",
                        "status": status,
                        "last_audited_at": None,
                    })
        except Exception as e:
            logger.warning(f"Failed to fetch campaigns for account {account_id}: {e}")
            print(f"[campaign-audit-summary] account={account_id} live_fetch_exception: {e}")

    # ---- Option C: campaign_landing_pages fallback for names ----
    lp_rows = db.query(CampaignLandingPage).filter(CampaignLandingPage.account_id == account_id).all()
    lp_map = {r.campaign_id: r for r in lp_rows}
    print(f"[campaign-audit-summary] account={account_id} landing_page_rows={len(lp_rows)}")
    for item in enabled_campaigns:
        cid = item["campaign_id"]
        if (not item["campaign_name"] or item["campaign_name"].startswith("Campaign #")) and lp_map.get(cid):
            item["campaign_name"] = lp_map[cid].campaign_name or item["campaign_name"]

    # Ensure any landing-page-only campaigns are included if nothing else found
    if not enabled_campaigns:
        for cid, lp in lp_map.items():
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            enabled_campaigns.append({
                "campaign_id": cid,
                "campaign_name": lp.campaign_name or f"Campaign #{cid}",
                "status": "ENABLED",
                "last_audited_at": None,
            })

    enabled_campaigns.sort(key=lambda x: x["campaign_name"])
    result = {
        "account_id": account_id,
        "account_name": account.name,
        "campaigns": enabled_campaigns,
    }
    print(f"[campaign-audit-summary] account={account_id} final_response_campaigns={len(enabled_campaigns)}")
    logger.info(f"Campaign audit summary for account {account_id}: {len(enabled_campaigns)} enabled campaigns returned")
    return result


@router.get("/adpulse/approval-queue/{account_id}/review")
def get_approval_queue_review(account_id: int, campaign_id: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """Return all pending recommendations for a single account grouped by type.

    Optionally filter to a single campaign via ?campaign_id=... for the
    campaign-level review panel.
    """
    _require_audit_review_access(user)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if user.role in ("user", "newuser") and account_id not in (user.assigned_account_ids() or []):
        raise HTTPException(status_code=403, detail="Access denied to this account")

    pending = db.query(PendingAction).filter(
        PendingAction.account_id == account_id,
        PendingAction.status == "pending",
    ).order_by(PendingAction.created_at.desc()).all()
    if campaign_id:
        pending = [a for a in pending if str(a.campaign_id) == str(campaign_id)]

    # Build campaign_id -> campaign_name map from Google Ads to fix legacy numeric campaign names
    campaign_name_map = _fetch_campaign_name_map(account)

    active_only = [a for a in pending if _normalize_campaign_status(a.campaign_status) == "ENABLED"]

    keywords_to_pause = _merge_keyword_actions(active_only, campaign_name_map)
    negatives_to_add = _merge_search_term_actions(active_only, campaign_name_map)
    budget_changes = []
    campaign_actions = []

    for action in active_only:
        nv = action.new_value or {}
        metrics = nv.get("metrics", {}) if isinstance(nv, dict) else {}
        raw_campaign_name = (nv.get("campaign_name") if isinstance(nv, dict) else None) or ""
        campaign_id = action.campaign_id or ""
        campaign_name = _display_campaign_name(raw_campaign_name or campaign_name_map.get(campaign_id, ""), campaign_id)
        conversions = metrics.get("conversions", 0) or 0

        if action.action_type in ("PAUSE_OR_REDUCE_BUDGET",):
            suggested = nv.get("suggested_budget") if isinstance(nv, dict) else None
            budget_changes.append({
                "id": action.id,
                "campaign_name": campaign_name,
                "campaign_id": campaign_id,
                "current_budget": action.account.budget if action.account else 0,
                "suggested_budget": suggested,
                "spend_30d": metrics.get("spend", 0) or 0,
                "clicks_30d": metrics.get("clicks", 0) or 0,
                "conversions_30d": conversions,
                "ctr": metrics.get("ctr", 0) or 0,
                "cpa": round(metrics.get("spend", 0) / conversions, 2) if conversions else None,
                "reason": action.reason or "",
                "campaign_status": action.campaign_status or "ENABLED",
            })

        elif action.action_type in ("PAUSE_CAMPAIGN", "ENABLE_CAMPAIGN", "ALERT_PERFORMANCE_ISSUE", "ALERT_SETUP_ISSUE", "ALERT_MISSING_LANDING_PAGE"):
            campaign_actions.append({
                "id": action.id,
                "campaign_name": campaign_name,
                "campaign_id": campaign_id,
                "action": action.action_type.lower().replace("_campaign", ""),
                "spend_30d": metrics.get("spend", 0) or 0,
                "clicks_30d": metrics.get("clicks", 0) or 0,
                "conversions_30d": conversions,
                "ctr": metrics.get("ctr", 0) or 0,
                "cpa": round(metrics.get("spend", 0) / conversions, 2) if conversions else None,
                "reason": action.reason or "",
                "campaign_status": action.campaign_status or "ENABLED",
            })

    # Merge budget/campaign duplicates if any
    budget_changes = _merge_generic_actions(budget_changes, key_fields=("campaign_id",))
    campaign_actions = _merge_generic_actions(campaign_actions, key_fields=("campaign_id",))

    # Default audit date = latest action created_at, else today
    audit_dt = active_only[0].created_at if active_only else datetime.utcnow()
    # Build campaign context: all keywords per campaign_id (flagged + clean)
    # Non-blocking: if Google Ads API fails, return empty context (modal still works)
    campaign_context = {}
    try:
        campaign_context = _build_campaign_keyword_context(account, active_only, campaign_name_map)
    except Exception as e:
        logger.warning(f"Failed to build campaign context for account {account_id}: {e}")
        campaign_context = {}

    return {
        "account_id": account_id,
        "account_name": account.name,
        "audit_date": audit_dt.strftime("%d %b %Y, %I:%M %p") if audit_dt else None,
        "keywords_to_pause": keywords_to_pause,
        "negatives_to_add": negatives_to_add,
        "budget_changes": budget_changes,
        "campaign_actions": campaign_actions,
        "campaign_context": campaign_context,
    }


@router.post("/adpulse/approval-queue/apply")
def apply_approval_queue_actions(req: BulkApplyRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """Process approved/rejected/dismissed recommendations in bulk."""
    _require_audit_review_access(user)
    results = []
    reviewer = req.reviewer or (user.email or user.role or "admin")
    now = datetime.utcnow()
    suppression_days = 30
    try:
        from backend.services.audit_settings import get_int_setting
        suppression_days = get_int_setting("smart_audit_rejection_suppression_days", db) or 30
    except Exception:
        pass

    # Flatten merged approvals/rejections/dismissals into individual DB ids
    def _flatten_ids(items, merged_field):
        ids = {item.id for item in items}
        for merged in merged_field:
            ids.update(merged.ids)
        return ids

    approved_ids = _flatten_ids(req.approved, req.merged_approved)
    rejected_ids = _flatten_ids(req.rejected, req.merged_rejected)
    dismissed_ids = _flatten_ids(req.dismissed, req.merged_dismissed)

    # Map custom_value per DB id (legacy single + merged)
    custom_by_id: Dict[int, float] = {}
    for item in req.approved:
        if item.custom_value is not None:
            custom_by_id[item.id] = item.custom_value
    for merged in req.merged_approved:
        for db_id in merged.ids:
            if merged.custom_value is not None:
                custom_by_id[db_id] = merged.custom_value

    # Track applied API mutations so we don't call Google Ads twice for merged items
    applied_mutations: Dict[str, Dict[str, Any]] = {}

    def _apply_once(action: PendingAction, custom_value: Optional[float] = None) -> Dict[str, Any]:
        """Apply the Google Ads mutation once per campaign/keyword/action_type."""
        nv = action.new_value or {}
        if not isinstance(nv, dict):
            nv = {}
        if action.action_type in ("SMART_PAUSE_KEYWORD", "PAUSE_KEYWORD"):
            mutation_key = f"pause_keyword::{action.campaign_id}::{action.keyword}"
        elif action.action_type in ("SMART_ADD_NEGATIVE_KEYWORD", "ADD_NEGATIVE_KEYWORD"):
            mutation_key = f"negative::{action.campaign_id}::{action.keyword}"
        elif action.action_type == "PAUSE_OR_REDUCE_BUDGET":
            mutation_key = f"budget::{action.campaign_id}"
        else:
            mutation_key = f"other::{action.action_type}::{action.campaign_id}"

        if mutation_key in applied_mutations:
            return applied_mutations[mutation_key]

        result = {"success": False, "error": "Unknown action type"}
        account = db.query(Account).filter(Account.id == action.account_id).first()
        if not account:
            result = {"success": False, "error": "Account not found"}
            applied_mutations[mutation_key] = result
            return result

        try:
            if action.action_type in ("SMART_PAUSE_KEYWORD", "PAUSE_KEYWORD") and action.platform == "google" and account.google_is_live:
                connector = get_connector(account, platform="google")
                if connector and connector.is_valid:
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
                new_budget = custom_value if custom_value is not None else nv.get("suggested_budget")
                if new_budget is None:
                    result = {"success": False, "error": "No budget value provided"}
                elif account.google_is_live:
                    connector = get_connector(account, platform="google")
                    if connector and connector.is_valid:
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

        applied_mutations[mutation_key] = result
        return result

    def _log_action_event(action: PendingAction, outcome: str, message: str):
        if outcome not in ("applied", "failed"):
            return
        account = db.query(Account).filter(Account.id == action.account_id).first()
        account_name = account.name if account else None
        campaign_name = None
        if action.new_value and isinstance(action.new_value, dict):
            campaign_name = action.new_value.get("campaign_name")
        if not campaign_name:
            campaign_name = action.campaign_id or ""
        user_name = user.full_name or user.email
        if outcome == "failed":
            log_activity(
                module="AdPulse", action="Recommendation Apply Failed",
                description=f"Failed to apply {action.action_type} for '{action.keyword or action.campaign_id}' in campaign {campaign_name}: {message}",
                user_id=user.id, user_name=user_name,
                account_id=action.account_id, account_name=account_name,
                entity_type="keyword" if action.keyword else "campaign",
                entity_id=action.keyword or action.campaign_id or "",
                details={"action_type": action.action_type, "campaign_id": action.campaign_id, "error": message},
                db=db,
            )
            return
        if action.action_type in ("SMART_PAUSE_KEYWORD", "PAUSE_KEYWORD"):
            log_activity(
                module="AdPulse", action="Keyword Paused",
                description=f"Paused keyword '{action.keyword}' in campaign {campaign_name}",
                user_id=user.id, user_name=user_name,
                account_id=action.account_id, account_name=account_name,
                entity_type="keyword", entity_id=action.keyword or "",
                details={"campaign_id": action.campaign_id, "campaign_name": campaign_name, "ad_group_id": action.adset_id},
                db=db,
            )
        elif action.action_type in ("SMART_ADD_NEGATIVE_KEYWORD", "ADD_NEGATIVE_KEYWORD"):
            log_activity(
                module="AdPulse", action="Negative Added",
                description=f"Added negative keyword '{action.keyword}' to campaign {campaign_name}",
                user_id=user.id, user_name=user_name,
                account_id=action.account_id, account_name=account_name,
                entity_type="keyword", entity_id=action.keyword or "",
                details={"campaign_id": action.campaign_id, "campaign_name": campaign_name, "match_type": action.match_type},
                db=db,
            )
        elif action.action_type == "PAUSE_OR_REDUCE_BUDGET":
            old_budget = action.new_value.get("current_budget") if isinstance(action.new_value, dict) else None
            new_budget = custom_by_id.get(action.id) if action.new_value and isinstance(action.new_value, dict) else None
            if new_budget is None and isinstance(action.new_value, dict):
                new_budget = action.new_value.get("suggested_budget")
            log_activity(
                module="AdPulse", action="Budget Changed",
                description=f"Changed budget for {campaign_name} from INR {old_budget or 'unknown'} to INR {new_budget or 'unknown'}",
                user_id=user.id, user_name=user_name,
                account_id=action.account_id, account_name=account_name,
                entity_type="campaign", entity_id=action.campaign_id or "",
                details={"campaign_id": action.campaign_id, "campaign_name": campaign_name, "old_budget": old_budget, "new_budget": new_budget},
                db=db,
            )
        elif action.action_type in ("PAUSE_CAMPAIGN", "ENABLE_CAMPAIGN"):
            log_activity(
                module="AdPulse", action="Campaign Paused" if action.action_type == "PAUSE_CAMPAIGN" else "Campaign Enabled",
                description=f"{('Paused' if action.action_type == 'PAUSE_CAMPAIGN' else 'Enabled')} campaign {campaign_name}",
                user_id=user.id, user_name=user_name,
                account_id=action.account_id, account_name=account_name,
                entity_type="campaign", entity_id=action.campaign_id or "",
                details={"campaign_id": action.campaign_id, "campaign_name": campaign_name},
                db=db,
            )

    def _mark_action(action: PendingAction, outcome: str, message: str):
        now = datetime.utcnow()
        if outcome == "applied":
            action.status = "applied"
            action.applied_at = now
            action.error_message = None
        else:
            action.status = "failed" if outcome == "failed" else action.status
            action.error_message = message
        action.reviewed_by = reviewer
        action.reviewed_at = now
        results.append({"id": action.id, "status": outcome, "message": message})
        _log_action_event(action, outcome, message)

    # Process all approved DB ids (legacy + flattened merged)
    for db_id in approved_ids:
        action = db.query(PendingAction).filter(PendingAction.id == db_id).first()
        if not action:
            results.append({"id": db_id, "status": "failed", "message": "Action not found"})
            continue
        if action.status != "pending":
            results.append({"id": db_id, "status": "skipped", "message": f"Already {action.status}"})
            continue

        result = _apply_once(action, custom_by_id.get(db_id))
        if result.get("success"):
            _mark_action(action, "applied", result.get("message", "Applied"))
        else:
            _mark_action(action, "failed", result.get("error", "Unknown error"))

    # Rejected items: set rejected + suppress search terms for 30 days
    rejected_actions = []
    for db_id in rejected_ids:
        action = db.query(PendingAction).filter(PendingAction.id == db_id).first()
        if action and action.status == "pending":
            action.status = "rejected"
            action.reviewed_by = reviewer
            action.reviewed_at = now
            rejected_actions.append(action)
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

    # Log rejections
    for action in rejected_actions:
        account = db.query(Account).filter(Account.id == action.account_id).first()
        campaign_name = action.new_value.get("campaign_name") if isinstance(action.new_value, dict) else None
        if not campaign_name:
            campaign_name = action.campaign_id or ""
        entity_label = action.keyword or action.campaign_id or ""
        log_activity(
            module="AdPulse",
            action="Recommendation Rejected",
            description=f"Rejected recommendation: {entity_label} in campaign {campaign_name}",
            user_id=user.id,
            user_name=user.full_name or user.email,
            account_id=action.account_id,
            account_name=account.name if account else None,
            entity_type="keyword" if action.keyword else "campaign",
            entity_id=entity_label,
            details={"action_type": action.action_type, "campaign_id": action.campaign_id, "campaign_name": campaign_name},
            db=db,
        )

    # Log smart approve if multiple items approved at once
    if len(approved_ids) > 1:
        # Determine account and campaign context from first approved action
        first_action = db.query(PendingAction).filter(PendingAction.id.in_(list(approved_ids))).first()
        account = None
        if first_action:
            account = db.query(Account).filter(Account.id == first_action.account_id).first()
        log_activity(
            module="AdPulse",
            action="Smart Approve",
            description=f"Smart Approved {len(approved_ids)} items for {account.name if account else 'account'}",
            user_id=user.id,
            user_name=user.full_name or user.email,
            account_id=account.id if account else None,
            account_name=account.name if account else None,
            entity_type="campaign",
            entity_id=first_action.campaign_id if first_action else "",
            details={"approved_count": len(approved_ids)},
            db=db,
        )

    # Dismissed items: mark as dismissed (will be re-evaluated next audit)
    for db_id in dismissed_ids:
        action = db.query(PendingAction).filter(PendingAction.id == db_id).first()
        if action and action.status == "pending":
            action.status = "dismissed"
            action.reviewed_by = reviewer
            action.reviewed_at = now

    db.commit()

    return {
        "results": results,
        "rejected_count": len(rejected_ids),
        "dismissed_count": len(dismissed_ids),
        "applied_count": sum(1 for r in results if r["status"] == "applied"),
        "failed_count": sum(1 for r in results if r["status"] == "failed"),
    }
