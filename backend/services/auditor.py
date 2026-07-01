"""
Expanded AI Auditor for Google Ads and Meta Ads accounts.
Generates pending optimization actions based on rules:
1. Campaign setup health (tracking, landing page, negatives, match types)
2. Campaign performance alerts (budget burn, high CPA, no conversions)
3. Keyword analysis (low quality, expensive, duplicate, underperforming)
4. Search term analysis (irrelevant terms, high spend no conversions)
"""
import random
import logging
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse
from sqlalchemy.orm import Session
from backend.db.database import SessionLocal
from backend.db.models import Account, AccountType, PendingAction, SuppressedSearchTerm
from backend.services.connectors import get_connector
from backend.services.audit_settings import get_int_setting

NEGATIVE_INTENT_WORDS = [
    "free", "job", "jobs", "salary", "download", "tutorial", "tutorials",
    "crack", "what is", "how to", "definition", "ppt", "pdf", "question paper",
    "question papers", "time table", "syllabus", "notes",
]

logger = logging.getLogger("AdOptima")


# ------------------------ Audit entrypoints ------------------------

def audit_account(account_id: int, start_date: Optional[str] = None, end_date: Optional[str] = None, platform: Optional[str] = None) -> Dict[str, Any]:
    """Run a full audit on a single account and create pending actions."""
    db = SessionLocal()
    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return {"error": "Account not found"}

        target_platform = _resolve_platform(account, platform)
        if not target_platform:
            return {"error": "No platform enabled for this account"}

        actions = []
        if target_platform == "google" and account.has_google:
            actions = _audit_google(account, db, start_date=start_date, end_date=end_date)
        elif target_platform == "meta" and account.has_meta:
            actions = _audit_meta(account, db, start_date=start_date, end_date=end_date)

        return {
            "account_id": account_id,
            "account_name": account.name,
            "platform": target_platform,
            "actions_generated": len(actions),
            "actions": [a.to_dict() for a in actions],
        }
    finally:
        db.close()


def audit_all_accounts(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    """Run audits on all active accounts."""
    db = SessionLocal()
    try:
        accounts = db.query(Account).filter(Account.is_active == True).all()
        results = []
        total_actions = 0
        for account in accounts:
            for platform in ["google", "meta"]:
                if (platform == "google" and account.has_google) or (platform == "meta" and account.has_meta):
                    res = audit_account(account.id, start_date=start_date, end_date=end_date, platform=platform)
                    total_actions += res.get("actions_generated", 0)
                    results.append(res)
        return {
            "accounts_audited": len(results),
            "total_actions_generated": total_actions,
            "results": results,
        }
    finally:
        db.close()


def _resolve_platform(account: Account, platform: Optional[str]) -> Optional[str]:
    if platform in ("google", "meta"):
        return platform
    if account.account_type == AccountType.GOOGLE:
        return "google"
    if account.account_type == AccountType.META:
        return "meta"
    if account.has_google:
        return "google"
    if account.has_meta:
        return "meta"
    return None


# ------------------------ Google Ads audit ------------------------

def _audit_google(account: Account, db: Session, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[PendingAction]:
    """Full Google Ads audit using live data only."""
    platform_live = account.google_is_live
    campaigns, keywords, search_terms = [], [], []
    if platform_live:
        try:
            connector = get_connector(account, platform="google", start_date=start_date, end_date=end_date)
            if connector and connector.is_valid:
                campaigns = connector.fetch_campaigns()
                search_terms = connector.fetch_search_terms()
        except Exception as e:
            logger.warning(f"Live Google connector failed for account {account.id}: {e}")

    new_actions = []

    # 1. Campaign setup + performance alerts
    for camp in campaigns:
        new_actions.extend(_audit_google_campaign_setup(account, camp))
        new_actions.extend(_audit_google_campaign_performance(account, camp))

    # 2. Keyword analysis
    account_avg_cpa = _account_avg_cpa(campaigns)
    for kw in keywords:
        action = _audit_keyword(account, kw, account_avg_cpa)
        if action:
            new_actions.append(action)

    # 3. Search term analysis
    for term in search_terms:
        action = _audit_search_term(account, term)
        if action:
            new_actions.append(action)

    for action in new_actions:
        db.add(action)
    db.commit()
    for action in new_actions:
        db.refresh(action)
    return new_actions


def _audit_google_campaign_setup(account: Account, camp: Dict[str, Any]) -> List[PendingAction]:
    actions = []
    camp_id = camp["id"]
    camp_name = camp["name"]

    if not camp.get("conversion_tracking_enabled", True):
        actions.append(PendingAction(
            account_id=account.id,
            action_type="ALERT_SETUP_ISSUE",
            platform="google",
            campaign_id=camp_id,
            reason=f"Campaign '{camp_name}' is missing conversion tracking. Set up Google Ads conversion actions or import GA4 goals.",
            new_value={"issue": "conversion_tracking_missing", "campaign_name": camp_name},
            status="pending",
        ))

    if camp.get("landing_page_status") == 404:
        actions.append(PendingAction(
            account_id=account.id,
            action_type="FIX_LANDING_PAGE",
            platform="google",
            campaign_id=camp_id,
            reason=f"Landing page for '{camp_name}' returns 404 ({camp.get('landing_page_url', '')}). Fix URL or pause ads.",
            new_value={"issue": "landing_page_404", "url": camp.get("landing_page_url", ""), "campaign_name": camp_name},
            status="pending",
        ))

    if not camp.get("issues") or "no_negative_keywords" in camp.get("issues", []):
        actions.append(PendingAction(
            account_id=account.id,
            action_type="ALERT_SETUP_ISSUE",
            platform="google",
            campaign_id=camp_id,
            reason=f"Campaign '{camp_name}' has no negative keywords. Add common negatives (free, jobs, tutorials) to prevent budget waste.",
            new_value={"issue": "no_negative_keywords", "campaign_name": camp_name},
            status="pending",
        ))

    if "only_broad_match" in camp.get("issues", []):
        actions.append(PendingAction(
            account_id=account.id,
            action_type="ALERT_SETUP_ISSUE",
            platform="google",
            campaign_id=camp_id,
            reason=f"Campaign '{camp_name}' uses only Broad Match keywords. Add Phrase and Exact match keywords and review search terms regularly.",
            new_value={"issue": "only_broad_match", "campaign_name": camp_name},
            status="pending",
        ))

    parsed = urlparse(camp.get("landing_page_url", ""))
    if parsed.query and "utm_source" not in parsed.query:
        actions.append(PendingAction(
            account_id=account.id,
            action_type="ALERT_SETUP_ISSUE",
            platform="google",
            campaign_id=camp_id,
            reason=f"Campaign '{camp_name}' landing page URL is missing UTM parameters ({camp.get('landing_page_url', '')}). Add utm_source, utm_medium, utm_campaign for attribution.",
            new_value={"issue": "missing_utm", "url": camp.get("landing_page_url", ""), "campaign_name": camp_name},
            status="pending",
        ))

    return actions


def _audit_google_campaign_performance(account: Account, camp: Dict[str, Any]) -> List[PendingAction]:
    actions = []
    camp_id = camp["id"]
    camp_name = camp["name"]
    spend = camp.get("spend", 0)
    budget = camp.get("budget", 0)
    conversions = camp.get("conversions", 0)
    ctr = camp.get("ctr", 0)
    cpa = camp.get("cpa", 0)
    target_cpa = camp.get("target_cpa", 0)

    if budget > 0 and spend / budget > 0.8 and conversions == 0:
        actions.append(PendingAction(
            account_id=account.id,
            action_type="PAUSE_OR_REDUCE_BUDGET",
            platform="google",
            campaign_id=camp_id,
            reason=f"Campaign '{camp_name}' spent {round((spend/budget)*100,1)}% of budget with zero conversions. Consider pausing or reducing budget.",
            estimated_savings=round(spend * 0.3, 2),
            new_value={"suggested_budget": round(budget * 0.5, 2), "campaign_name": camp_name},
            status="pending",
        ))
    elif conversions == 0 and spend > 5000:
        actions.append(PendingAction(
            account_id=account.id,
            action_type="ALERT_PERFORMANCE_ISSUE",
            platform="google",
            campaign_id=camp_id,
            reason=f"Campaign '{camp_name}' spent Rs {spend:,.0f} with zero conversions. Check landing page, targeting, and keywords.",
            new_value={"campaign_name": camp_name, "spend": spend},
            status="pending",
        ))

    if target_cpa > 0 and cpa > target_cpa * 1.5:
        actions.append(PendingAction(
            account_id=account.id,
            action_type="REDUCE_BID",
            platform="google",
            campaign_id=camp_id,
            reason=f"Campaign '{camp_name}' CPA (Rs {cpa:,.0f}) is {round((cpa/target_cpa)*100,0)}% of target CPA (Rs {target_cpa:,.0f}). Reduce bids or tighten targeting.",
            estimated_savings=round(spend * 0.2, 2),
            new_value={"suggested_bid_reduction_pct": 20, "campaign_name": camp_name},
            status="pending",
        ))

    if ctr < 1.0 and camp.get("status") == "ENABLED":
        actions.append(PendingAction(
            account_id=account.id,
            action_type="ALERT_PERFORMANCE_ISSUE",
            platform="google",
            campaign_id=camp_id,
            reason=f"Campaign '{camp_name}' has low CTR ({ctr:.2f}%). Improve ad copy relevance or tighten keyword targeting.",
            new_value={"ctr": ctr, "campaign_name": camp_name},
            status="pending",
        ))

    if camp.get("status") == "PAUSED" and spend > 1000:
        actions.append(PendingAction(
            account_id=account.id,
            action_type="ALERT_PERFORMANCE_ISSUE",
            platform="google",
            campaign_id=camp_id,
            reason=f"Campaign '{camp_name}' is paused but has historical spend. Review if it should be re-enabled or budget reallocated.",
            status="pending",
        ))

    return actions


def _account_avg_cpa(campaigns: List[Dict[str, Any]]) -> float:
    total_spend = sum(c.get("spend", 0) for c in campaigns)
    total_conversions = sum(c.get("conversions", 0) for c in campaigns)
    return round(total_spend / total_conversions, 2) if total_conversions else 0.0


def _audit_keyword(account: Account, kw: Dict[str, Any], account_avg_cpa: float) -> Optional[PendingAction]:
    spend = kw.get("spend", 0)
    conversions = kw.get("conversions", 0)
    cpa = kw.get("cpa", 0)
    ctr = kw.get("ctr", 0)
    quality_score = kw.get("quality_score", 0)
    text = kw.get("text", "")
    match_type = kw.get("match_type", "BROAD")

    if spend > 3000 and conversions == 0:
        return PendingAction(
            account_id=account.id,
            action_type="PAUSE_KEYWORD",
            platform="google",
            campaign_id=kw.get("campaign_id", ""),
            keyword=text,
            match_type=match_type,
            reason=f"Keyword '{text}' spent Rs {spend:,.0f} with no conversions. Consider pausing or adding as negative.",
            estimated_savings=round(spend * 0.8, 2),
            new_value={"criterion_id": kw.get("criterion_id", ""), "campaign_name": kw.get("campaign_name", ""), "ad_group_id": kw.get("ad_group_id", "")},
            status="pending",
        )

    if account_avg_cpa > 0 and cpa > account_avg_cpa * 1.5 and conversions > 0:
        return PendingAction(
            account_id=account.id,
            action_type="REDUCE_BID",
            platform="google",
            campaign_id=kw.get("campaign_id", ""),
            keyword=text,
            match_type=match_type,
            reason=f"Keyword '{text}' CPA (Rs {cpa:,.0f}) is {round((cpa/account_avg_cpa)*100,0)}% higher than account average (Rs {account_avg_cpa:,.0f}). Reduce bid.",
            estimated_savings=round(spend * 0.15, 2),
            new_value={"suggested_bid_reduction_pct": 15, "criterion_id": kw.get("criterion_id", ""), "ad_group_id": kw.get("ad_group_id", "")},
            status="pending",
        )

    if quality_score <= 3 and spend > 1000:
        return PendingAction(
            account_id=account.id,
            action_type="ALERT_KEYWORD_QUALITY",
            platform="google",
            campaign_id=kw.get("campaign_id", ""),
            keyword=text,
            match_type=match_type,
            reason=f"Keyword '{text}' has low Quality Score ({quality_score}/10) and spend. Improve ad relevance, landing page, or pause keyword.",
            new_value={"quality_score": quality_score, "criterion_id": kw.get("criterion_id", ""), "ad_group_id": kw.get("ad_group_id", "")},
            status="pending",
        )

    if ctr < 1.0 and kw.get("impressions", 0) > 1000:
        return PendingAction(
            account_id=account.id,
            action_type="ALERT_KEYWORD_RELEVANCE",
            platform="google",
            campaign_id=kw.get("campaign_id", ""),
            keyword=text,
            match_type=match_type,
            reason=f"Keyword '{text}' has low CTR ({ctr:.2f}%) despite high impressions. Check ad copy/keyword relevance or tighten match type.",
            new_value={"ctr": ctr, "criterion_id": kw.get("criterion_id", ""), "ad_group_id": kw.get("ad_group_id", "")},
            status="pending",
        )

    return None


def _audit_search_term(account: Account, term: Dict[str, Any]) -> Optional[PendingAction]:
    lower_term = term.get("term", "").lower()
    cost = term.get("cost", 0)
    conversions = term.get("conversions", 0)
    ctr = term.get("ctr", 0)
    impressions = term.get("impressions", 0)

    reasons = []
    if conversions == 0 and cost > 500:
        reasons.append(f"High spend (Rs {cost:,.0f}) with no conversions")
    if ctr < 1.5 and impressions > 500:
        reasons.append(f"Low CTR ({ctr:.2f}%) - poor relevance")
    for word in NEGATIVE_INTENT_WORDS:
        if word in lower_term:
            reasons.append(f"Unproductive term contains '{word}'")
            break
    if any(w in lower_term for w in ["college", "university", "fees", "address", "admission"]):
        brand_terms = ["dsu", "dayananda", account.name.lower().split()[0]]
        if not any(b in lower_term for b in brand_terms):
            reasons.append("Generic / competitor intent")

    if reasons:
        return PendingAction(
            account_id=account.id,
            action_type="ADD_NEGATIVE_KEYWORD",
            platform="google",
            campaign_id=term.get("campaign_id", ""),
            keyword=term["term"],
            match_type="EXACT",
            reason="; ".join(reasons),
            estimated_savings=round(cost * 0.8, 2),
            status="pending",
        )
    return None


# ------------------------ Meta Ads audit ------------------------

def _audit_meta(account: Account, db: Session, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[PendingAction]:
    """Meta Ads audit using live data only."""
    platform_live = account.meta_is_live
    campaigns, adsets, ads = [], [], []
    if platform_live:
        connector = get_connector(account, platform="meta", start_date=start_date, end_date=end_date)
        if connector and connector.is_valid:
            campaigns = connector.fetch_campaigns()
            # TODO: fetch adsets + ads when live Meta support is added

    new_actions = []

    for camp in campaigns:
        new_actions.extend(_audit_meta_campaign(account, camp, adsets, ads))

    for action in new_actions:
        db.add(action)
    db.commit()
    for action in new_actions:
        db.refresh(action)
    return new_actions


def _audit_meta_campaign(account: Account, camp: Dict[str, Any], adsets: List[Dict[str, Any]], ads: List[Dict[str, Any]]) -> List[PendingAction]:
    actions = []
    camp_id = camp["id"]
    camp_name = camp["name"]
    spend = camp.get("spend", 0)
    budget = camp.get("budget", 0)
    conversions = camp.get("conversions", 0)
    ctr = camp.get("ctr", 0)
    cpa = camp.get("cpa", 0)
    target_cpa = camp.get("target_cpa", 0)

    if camp.get("pixel_status") != "ACTIVE":
        actions.append(PendingAction(
            account_id=account.id,
            action_type="ALERT_SETUP_ISSUE",
            platform="meta",
            campaign_id=camp_id,
            reason=f"Meta campaign '{camp_name}' pixel status is '{camp.get('pixel_status')}'. Verify pixel firing and event matching.",
            new_value={"issue": "pixel_not_active", "campaign_name": camp_name},
            status="pending",
        ))

    if budget > 0 and spend / budget > 0.8 and conversions == 0:
        actions.append(PendingAction(
            account_id=account.id,
            action_type="PAUSE_OR_REDUCE_BUDGET",
            platform="meta",
            campaign_id=camp_id,
            reason=f"Meta campaign '{camp_name}' spent {round((spend/budget)*100,1)}% of budget with zero conversions. Consider pausing or reducing budget.",
            estimated_savings=round(spend * 0.3, 2),
            new_value={"suggested_budget": round(budget * 0.5, 2), "campaign_name": camp_name},
            status="pending",
        ))

    if target_cpa > 0 and cpa > target_cpa * 1.5:
        actions.append(PendingAction(
            account_id=account.id,
            action_type="REDUCE_BID",
            platform="meta",
            campaign_id=camp_id,
            reason=f"Meta campaign '{camp_name}' CPA (Rs {cpa:,.0f}) is {round((cpa/target_cpa)*100,0)}% of target. Reduce bid or tighten audiences.",
            estimated_savings=round(spend * 0.2, 2),
            new_value={"suggested_bid_reduction_pct": 20, "campaign_name": camp_name},
            status="pending",
        ))

    if ctr < 0.8 and camp.get("status") == "ACTIVE":
        actions.append(PendingAction(
            account_id=account.id,
            action_type="ALERT_PERFORMANCE_ISSUE",
            platform="meta",
            campaign_id=camp_id,
            reason=f"Meta campaign '{camp_name}' has low CTR ({ctr:.2f}%). Refresh creative or tighten audience targeting.",
            new_value={"ctr": ctr, "campaign_name": camp_name},
            status="pending",
        ))

    # Ad-level checks
    camp_ads = [a for a in ads if a.get("campaign_id") == camp_id]
    for ad in camp_ads:
        url = ad.get("landing_page_url", "")
        if url and "utm_source" not in url:
            actions.append(PendingAction(
                account_id=account.id,
                action_type="ALERT_SETUP_ISSUE",
                platform="meta",
                campaign_id=camp_id,
                adset_id=ad.get("adset_id", ""),
                reason=f"Meta ad '{ad.get('name')}' URL missing UTM parameters: {url}. Add utm_source, utm_medium, utm_campaign.",
                new_value={"issue": "missing_utm", "url": url, "campaign_name": camp_name},
                status="pending",
            ))

    return actions


# ------------------------ Review / apply ------------------------

def list_pending_actions(db: Session = None) -> List[PendingAction]:
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    try:
        return db.query(PendingAction).filter(PendingAction.status == "pending").order_by(PendingAction.created_at.desc()).all()
    finally:
        if close_session:
            db.close()


def review_action(action_id: int, decision: str, reviewer: str = "admin") -> Dict[str, Any]:
    """Approve or reject a pending action."""
    db = SessionLocal()
    try:
        action = db.query(PendingAction).filter(PendingAction.id == action_id).first()
        if not action:
            return {"error": "Action not found"}
        if action.status != "pending":
            return {"error": f"Action already {action.status}"}

        from datetime import datetime, timedelta, date
        action.status = "approved" if decision == "approve" else "rejected"
        action.reviewed_by = reviewer
        action.reviewed_at = datetime.utcnow()

        if action.status == "approved":
            result = _apply_action(action, db)
            if result.get("success"):
                action.applied_at = datetime.utcnow()
                action.status = "applied"
            else:
                action.status = "failed"
                action.error_message = result.get("error")

        if action.status == "rejected" and action.action_type == "SMART_ADD_NEGATIVE_KEYWORD":
            # Suppress rejected search term for configured days so it is not re-flagged
            suppression_days = get_int_setting("smart_audit_rejection_suppression_days", db)
            suppressed_until = date.today() + timedelta(days=suppression_days)
            existing = db.query(SuppressedSearchTerm).filter(
                SuppressedSearchTerm.account_id == action.account_id,
                SuppressedSearchTerm.campaign_id == action.campaign_id,
                SuppressedSearchTerm.search_term == action.keyword,
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

        db.commit()
        db.refresh(action)
        return action.to_dict()
    finally:
        db.close()


def _apply_action(action: PendingAction, db: Session) -> Dict[str, Any]:
    """Apply an approved action to the live platform."""
    account = db.query(Account).filter(Account.id == action.account_id).first()
    if not account:
        return {"success": False, "error": "Account not found"}

    try:
        if action.action_type == "ADD_NEGATIVE_KEYWORD" and action.platform == "google":
            if account.google_is_live:
                connector = get_connector(account, platform="google")
                if connector and connector.is_valid:
                    return connector.apply_negative_keyword(
                        action.campaign_id or "",
                        action.keyword or "",
                        action.match_type or "EXACT",
                    )
                return {"success": False, "error": "Live Google connector not valid"}
            return {"success": False, "error": "Account is not live; cannot apply action"}

        if action.action_type == "SMART_ADD_NEGATIVE_KEYWORD" and action.platform == "google":
            if account.google_is_live:
                connector = get_connector(account, platform="google")
                if connector and connector.is_valid:
                    return connector.apply_negative_keyword(
                        action.campaign_id or "",
                        action.keyword or "",
                        action.match_type or "EXACT",
                    )
                return {"success": False, "error": "Live Google connector not valid"}
            return {"success": False, "error": "Account is not live; cannot apply action"}

        if action.action_type == "SMART_PAUSE_KEYWORD" and action.platform == "google":
            if account.google_is_live:
                connector = get_connector(account, platform="google")
                if connector and connector.is_valid:
                    new_value = action.new_value or {}
                    return connector.pause_keyword(
                        new_value.get("ad_group_id") or action.adset_id or "",
                        new_value.get("criterion_id") or "",
                    )
                return {"success": False, "error": "Live Google connector not valid"}
            return {"success": False, "error": "Account is not live; cannot apply action"}

        if action.action_type in ("PAUSE_OR_REDUCE_BUDGET", "REDUCE_BID", "PAUSE_KEYWORD", "FIX_LANDING_PAGE", "ALERT_SETUP_ISSUE", "ALERT_PERFORMANCE_ISSUE", "ALERT_KEYWORD_QUALITY", "ALERT_KEYWORD_RELEVANCE"):
            return {"success": True, "message": "Action logged for manual implementation"}

        return {"success": False, "error": "Unknown action type"}
    except Exception as e:
        return {"success": False, "error": str(e)}
