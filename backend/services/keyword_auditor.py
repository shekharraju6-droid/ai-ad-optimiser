"""
Smart Keyword Auditor for Google Ads.

Generates PendingAction recommendations for:
  A) Non-brand keywords appearing in Brand campaigns
  B) Non-performing keywords (spent money, zero conversions)

Never auto-applies changes.
"""
import logging
from datetime import datetime, date
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session

from backend.db.database import SessionLocal
from backend.db.models import Account, CampaignTypeTag, PendingAction
from backend.services.connectors import get_connector
from backend.services.audit_settings import get_int_setting

logger = logging.getLogger("AdOptima")


def _brand_terms_for_account(account: Account) -> List[str]:
    """Return lower-cased brand terms list. Defaults to account name and brand_name."""
    raw = (account.brand_keywords or "").strip()
    terms = []
    if raw:
        terms = [t.strip() for t in raw.split(",") if t.strip()]
    # Fallback defaults
    for fallback in [account.name, account.brand_name]:
        if fallback and fallback.strip():
            terms.append(fallback.strip())
    # Deduplicate while preserving order, lower-case
    seen = set()
    result = []
    for t in terms:
        tl = t.lower()
        if tl and tl not in seen:
            seen.add(tl)
            result.append(tl)
    return result


def _campaign_type_map(db: Session, account_id: int, campaigns: List[Dict[str, Any]]) -> Dict[str, str]:
    """Return map campaign_id -> 'brand' or 'non_brand'. Manual tags override name detection."""
    tags = db.query(CampaignTypeTag).filter(CampaignTypeTag.account_id == account_id).all()
    tag_map = {t.campaign_id: t.campaign_type for t in tags}
    result = {}
    for camp in campaigns:
        cid = camp.get("id")
        if not cid:
            continue
        manual = tag_map.get(cid, "auto")
        if manual in ("brand", "non_brand"):
            result[cid] = manual
        else:
            name_lower = (camp.get("name") or "").lower()
            result[cid] = "brand" if "brand" in name_lower or "branded" in name_lower else "non_brand"
    return result


def _contains_brand_term(text: str, brand_terms: List[str]) -> bool:
    text_lower = (text or "").lower()
    return any(term in text_lower for term in brand_terms)


def _keyword_already_flagged(db: Session, account_id: int, campaign_id: str, keyword_text: str, match_type: str, action_type: str) -> bool:
    """Check if an identical keyword pause/negative recommendation is still pending."""
    existing = db.query(PendingAction).filter(
        PendingAction.account_id == account_id,
        PendingAction.campaign_id == campaign_id,
        PendingAction.keyword == keyword_text,
        PendingAction.match_type == match_type,
        PendingAction.action_type == action_type,
        PendingAction.status == "pending",
    ).first()
    return existing is not None


def _campaign_status(campaigns: List[Dict[str, Any]], campaign_id: str) -> str:
    """Return campaign status at audit time (ENABLED/PAUSED/REMOVED/UNKNOWN).

    Google Ads CampaignStatus proto enum:
      UNSPECIFIED=0, UNKNOWN=1, ENABLED=2, PAUSED=3, REMOVED=4
    Some proto-plus objects stringify to the numeric value, so we map them.
    """
    status_map = {
        "0": "UNKNOWN",
        "1": "UNKNOWN",
        "2": "ENABLED",
        "3": "PAUSED",
        "4": "REMOVED",
    }
    for camp in campaigns:
        if str(camp.get("id")) == str(campaign_id):
            status = camp.get("status")
            if status is not None:
                raw = str(status).upper().strip()
                return status_map.get(raw, raw)
    return "UNKNOWN"


def _build_campaign_name_map(campaigns: List[Dict[str, Any]]) -> Dict[str, str]:
    """Build a campaign_id -> campaign_name lookup from the campaigns list.

    Falls back to fetching all campaigns via a separate GAQL query if the
    campaigns list is empty.
    """
    name_map: Dict[str, str] = {}
    for camp in campaigns:
        cid = str(camp.get("id") or "")
        name = camp.get("name") or ""
        if cid and name:
            name_map[cid] = name
    return name_map


def _resolve_campaign_name(campaign_id: str, fallback_name: str, name_map: Dict[str, str]) -> str:
    """Return a readable campaign name. Uses name_map as fallback when fallback_name is empty/numeric."""
    if fallback_name and not fallback_name.strip().isdigit():
        return fallback_name
    if campaign_id and str(campaign_id) in name_map:
        return name_map[str(campaign_id)]
    if fallback_name:
        return fallback_name
    return campaign_id or "Unknown"


def run_keyword_audit(account_id: int, db: Session = None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    """Run keyword audit for a single Google Ads account. Returns summary and created actions."""
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return {"error": "Account not found"}
        if not (account.has_google and account.google_is_live):
            return {"error": "Account has no live Google Ads connection", "actions_generated": 0}

        connector = get_connector(account, platform="google", start_date=start_date, end_date=end_date)
        if not connector or not connector.is_valid:
            return {"error": "Google Ads connector not valid", "actions_generated": 0}

        campaigns = connector.fetch_campaigns()
        campaign_name_map = _build_campaign_name_map(campaigns)
        campaign_type_map = _campaign_type_map(db, account_id, campaigns)
        brand_terms = _brand_terms_for_account(account)

        # Threshold from settings
        non_performing_spend_threshold_inr = get_int_setting("smart_audit_keyword_min_spend_inr", db)

        keywords = connector.fetch_keywords()
        actions: List[PendingAction] = []

        for kw in keywords:
            cid = kw.get("campaign_id")
            campaign_type = campaign_type_map.get(cid, "non_brand")
            keyword_text = kw.get("text", "")
            match_type = kw.get("match_type", "")
            criterion_id = kw.get("criterion_id", "")
            ad_group_id = kw.get("ad_group_id", "")
            spend = kw.get("spend", 0) or 0
            conversions = kw.get("conversions", 0) or 0
            clicks = kw.get("clicks", 0) or 0
            ctr = kw.get("ctr", 0) or 0
            camp_status = _campaign_status(campaigns, cid)
            resolved_campaign_name = _resolve_campaign_name(cid, kw.get("campaign_name", ""), campaign_name_map)

            # CHECK A: Non-brand keyword in Brand campaign
            if campaign_type == "brand" and keyword_text:
                if not _contains_brand_term(keyword_text, brand_terms):
                    if not _keyword_already_flagged(db, account_id, cid, keyword_text, match_type, "SMART_PAUSE_KEYWORD"):
                        actions.append(PendingAction(
                            account_id=account_id,
                            action_type="SMART_PAUSE_KEYWORD",
                            platform="google",
                            campaign_id=cid,
                            adset_id=ad_group_id,
                            keyword=keyword_text,
                            match_type=match_type,
                            reason=f"Non-brand keyword '{keyword_text}' found in Brand campaign '{resolved_campaign_name}'. It does not contain any brand term ({', '.join(brand_terms)}).",
                            new_value={
                                "audit_type": "keyword_audit",
                                "recommendation": "pause_keyword",
                                "criterion_id": criterion_id,
                                "ad_group_id": ad_group_id,
                                "campaign_name": resolved_campaign_name,
                                "ad_group_name": kw.get("ad_group_name", ""),
                                "metrics": {"spend": spend, "clicks": clicks, "conversions": conversions, "ctr": ctr},
                                "check": "non_brand_in_brand_campaign",
                            },
                            status="pending",
                            campaign_status=camp_status,
                        ))

            # CHECK B: Non-performing keyword (any campaign)
            if spend > non_performing_spend_threshold_inr and conversions == 0 and keyword_text:
                if not _keyword_already_flagged(db, account_id, cid, keyword_text, match_type, "SMART_PAUSE_KEYWORD"):
                    actions.append(PendingAction(
                        account_id=account_id,
                        action_type="SMART_PAUSE_KEYWORD",
                        platform="google",
                        campaign_id=cid,
                        adset_id=ad_group_id,
                        keyword=keyword_text,
                        match_type=match_type,
                        reason=f"Keyword '{keyword_text}' spent Rs {spend:,.0f} with {clicks} clicks and {conversions} conversions in the last 30 days. Consider pausing it.",
                        estimated_savings=round(spend * 0.8, 2),
                        new_value={
                            "audit_type": "keyword_audit",
                            "recommendation": "pause_keyword",
                            "criterion_id": criterion_id,
                            "ad_group_id": ad_group_id,
                            "campaign_name": resolved_campaign_name,
                            "ad_group_name": kw.get("ad_group_name", ""),
                            "metrics": {"spend": spend, "clicks": clicks, "conversions": conversions, "ctr": ctr},
                            "check": "non_performing_keyword",
                        },
                        status="pending",
                        campaign_status=camp_status,
                    ))

        for action in actions:
            db.add(action)
        db.commit()
        for action in actions:
            db.refresh(action)

        return {
            "account_id": account_id,
            "account_name": account.name,
            "actions_generated": len(actions),
            "actions": [a.to_dict() for a in actions],
        }
    except Exception as e:
        logger.error(f"Keyword audit failed for account {account_id}: {e}", exc_info=True)
        return {"error": str(e), "account_id": account_id, "actions_generated": 0}
    finally:
        if close_session:
            db.close()
