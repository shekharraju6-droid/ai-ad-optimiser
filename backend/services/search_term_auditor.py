"""
Smart Search Term Auditor for Google Ads.

Uses Gemini to classify search terms as RELEVANT or IRRELEVANT per campaign,
then creates PendingAction recommendations to add EXACT negative keywords
at the campaign level. No auto-application.

Enhanced with:
  - Landing page context (crawled summary per campaign)
  - Business context + negative rules per account
  - Past approved/rejected patterns for feedback loop
  - Confidence scoring (HIGH/MEDIUM/LOW + 0-100)
"""
import json
import logging
import time
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session

from backend.db.database import SessionLocal
from backend.db.models import Account, CampaignTypeTag, PendingAction, SuppressedSearchTerm
from backend.services.ai_client import get_gemini_client
from backend.services.connectors import get_connector
from backend.services.audit_settings import get_int_setting
from backend.services.landing_page_service import get_landing_page_summary
from google.genai import types

logger = logging.getLogger("AdOptima")


def _brand_terms_for_account(account: Account) -> str:
    raw = (account.brand_keywords or "").strip()
    terms = []
    if raw:
        terms = [t.strip() for t in raw.split(",") if t.strip()]
    for fallback in [account.name, account.brand_name]:
        if fallback and fallback.strip():
            terms.append(fallback.strip())
    seen = set()
    result = []
    for t in terms:
        tl = t.lower()
        if tl and tl not in seen:
            seen.add(tl)
            result.append(t)
    return ", ".join(result) if result else account.name or "the client"


def _campaign_type(campaign_name: str, tags_map: Dict[str, str]) -> str:
    manual = tags_map.get(campaign_name)
    if manual in ("brand", "non_brand"):
        return manual
    name_lower = (campaign_name or "").lower()
    return "brand" if "brand" in name_lower or "branded" in name_lower else "non_brand"


def _is_suppressed(db: Session, account_id: int, campaign_id: str, term: str) -> bool:
    today = date.today()
    row = db.query(SuppressedSearchTerm).filter(
        SuppressedSearchTerm.account_id == account_id,
        SuppressedSearchTerm.campaign_id == campaign_id,
        SuppressedSearchTerm.search_term == term,
        SuppressedSearchTerm.suppressed_until >= today,
    ).first()
    return row is not None


def _build_campaign_name_map(campaigns: List[Dict[str, Any]]) -> Dict[str, str]:
    """Build a campaign_id -> campaign_name lookup from the campaigns list."""
    name_map: Dict[str, str] = {}
    for camp in campaigns:
        cid = str(camp.get("id") or "")
        name = camp.get("name") or ""
        if cid and name:
            name_map[cid] = name
    return name_map


def _resolve_campaign_name(campaign_id: str, fallback_name: str, name_map: Dict[str, str]) -> str:
    """Return a readable campaign name, falling back to name_map when fallback_name is empty/numeric."""
    if fallback_name and not fallback_name.strip().isdigit():
        return fallback_name
    if campaign_id and str(campaign_id) in name_map:
        return name_map[str(campaign_id)]
    if fallback_name:
        return fallback_name
    return campaign_id or "Unknown"


def _already_pending(db: Session, account_id: int, campaign_id: str, term: str) -> bool:
    existing = db.query(PendingAction).filter(
        PendingAction.account_id == account_id,
        PendingAction.campaign_id == campaign_id,
        PendingAction.keyword == term,
        PendingAction.action_type == "SMART_ADD_NEGATIVE_KEYWORD",
        PendingAction.status == "pending",
    ).first()
    return existing is not None


def _past_patterns(db: Session, account_id: int, campaign_id: str) -> Dict[str, List[str]]:
    """Return past approved (confirmed irrelevant) and rejected (actually relevant) search terms.

    Looks back 90 days. Limits each list to 50 items.
    """
    cutoff = datetime.utcnow() - timedelta(days=90)
    rows = db.query(PendingAction).filter(
        PendingAction.account_id == account_id,
        PendingAction.campaign_id == campaign_id,
        PendingAction.action_type.in_(("SMART_ADD_NEGATIVE_KEYWORD", "ADD_NEGATIVE_KEYWORD")),
        PendingAction.status.in_(("applied", "rejected")),
        PendingAction.created_at >= cutoff,
    ).all()
    approved = []
    rejected = []
    for r in rows:
        term = r.keyword or ""
        if not term:
            continue
        if r.status == "applied" and len(approved) < 50:
            approved.append(term)
        elif r.status == "rejected" and len(rejected) < 50:
            rejected.append(term)
    return {"approved": approved, "rejected": rejected}


def _classify_search_terms_batch(
    client,
    account: Account,
    campaign_name: str,
    campaign_id: str,
    terms_with_metrics: List[Dict[str, Any]],
    db: Session,
) -> List[Dict[str, Any]]:
    """Send up to 100 search terms to Gemini and return classifications with confidence."""
    if not terms_with_metrics:
        return []

    brand_terms = _brand_terms_for_account(account)
    client_name = account.name or "the client"
    category = account.category.name if account.category else (account.group.name if account.group else "general")
    business_context = (account.business_context or "").strip() or "Not provided"
    negative_rules = (account.negative_rules or "").strip() or "Not provided"

    # Landing page summary
    lp_summary_text = "Not available — landing page was not crawled"
    try:
        lp = get_landing_page_summary(db, account.id, campaign_id)
        if lp and lp.get("summary"):
            lp_summary_text = json.dumps(lp["summary"], ensure_ascii=False, indent=2)
        elif lp and lp.get("url"):
            lp_summary_text = f"Landing page URL: {lp['url']} (not yet crawled)"
    except Exception:
        pass

    # Past patterns
    past = _past_patterns(db, account.id, campaign_id)
    past_approved = ", ".join(past["approved"]) if past["approved"] else "None"
    past_rejected = ", ".join(past["rejected"]) if past["rejected"] else "None"

    lines = []
    for t in terms_with_metrics:
        lines.append(f"- '{t['term']}' | clicks={t['clicks']} | spend=Rs {t['spend']:.0f} | impressions={t['impressions']} | conversions={t['conversions']}")
    terms_block = "\n".join(lines)

    prompt = f"""You are a Google Ads search term auditor.

CLIENT INFORMATION:
Name: {client_name}
Category: {category}
Brand terms: {brand_terms}

BUSINESS CONTEXT (provided by the account manager):
{business_context}

ALWAYS IRRELEVANT RULES:
{negative_rules}

CAMPAIGN: {campaign_name}

LANDING PAGE SUMMARY:
{lp_summary_text}

PAST PATTERNS:
The following search terms were previously REJECTED by the human reviewer (meaning the AI incorrectly flagged them as irrelevant — they are actually RELEVANT):
{past_rejected}

The following search terms were previously APPROVED by the human reviewer (confirmed irrelevant):
{past_approved}

Learn from these past decisions. Do not repeat mistakes the human already corrected.

TASK:
For each search term below, classify as RELEVANT or IRRELEVANT and assign a confidence score.

A search term is IRRELEVANT if:
- It has no connection to what the landing page offers
- It matches any "always irrelevant" rule
- It shows intent for something the client does NOT offer (e.g. "free" for a paid service)
- It is about a competitor
- It is geographically irrelevant
- Past approved negatives confirm similar terms are bad

A search term is RELEVANT if:
- It relates to the landing page product/service
- It shows purchase/enquiry intent matching the campaign
- Past rejections confirm similar terms are actually good
- When in doubt, lean toward RELEVANT

CONFIDENCE SCORING:
- HIGH (90-100%): Very clear. The term is obviously irrelevant or obviously relevant. Landing page context and past patterns strongly support the classification.
- MEDIUM (60-89%): Likely correct but some ambiguity. The term could be interpreted differently.
- LOW (below 60%): Uncertain. The term is borderline. Human review strongly recommended.

Return ONLY a valid JSON array:
[
  {{
    "search_term": "exact search term",
    "classification": "RELEVANT" or "IRRELEVANT",
    "confidence": "HIGH" or "MEDIUM" or "LOW",
    "confidence_score": 85,
    "reason": "brief explanation referencing the landing page content or business context"
  }}
]

Search terms to classify:
{terms_block}
"""

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    system_instruction="You are a precise Google Ads search term classifier. Return only valid JSON. Never include explanations outside the JSON array.",
                ),
            )
            text = response.text if hasattr(response, "text") else ""
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                logger.warning(f"Gemini returned non-array for search term classification: {type(parsed)}")
                return []
            return parsed
        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = any(code in err_str for code in ["429", "503", "quota", "unavailable", "resource_exhausted"])
            if is_rate_limit and attempt < max_retries - 1:
                wait_seconds = 3
                logger.warning(
                    f"Gemini rate limit/unavailable for campaign '{campaign_name}' (attempt {attempt + 1}/{max_retries}): {e}. "
                    f"Retrying in {wait_seconds}s..."
                )
                time.sleep(wait_seconds)
                continue
            logger.error(f"Gemini search term classification failed for campaign '{campaign_name}': {e}", exc_info=True)
            return []


def run_search_term_audit(account_id: int, db: Session = None, start_date: Optional[str] = None, end_date: Optional[str] = None, campaign_id: Optional[str] = None) -> Dict[str, Any]:
    """Run search term audit for a single Google Ads account, optionally filtered to one campaign."""
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
        # If a single campaign is requested, only audit that campaign
        if campaign_id:
            campaigns = [c for c in campaigns if str(c.get("id")) == str(campaign_id)]
            if not campaigns:
                return {"error": f"Campaign {campaign_id} not found or not enabled", "actions_generated": 0}
        campaign_name_map = _build_campaign_name_map(campaigns)

        tags = db.query(CampaignTypeTag).filter(CampaignTypeTag.account_id == account_id).all()
        tags_map = {t.campaign_id: t.campaign_type for t in tags}

        # Thresholds from settings
        min_clicks = get_int_setting("smart_audit_search_term_min_clicks", db)
        min_spend = get_int_setting("smart_audit_search_term_min_spend_inr", db)

        search_terms = connector.fetch_search_terms()

        # Group by campaign and capture campaign status
        by_campaign: Dict[str, Dict[str, Any]] = {}
        for term in search_terms:
            cid = term.get("campaign_id")
            if not cid:
                continue
            # If filtering to a single campaign, skip other campaigns
            if campaign_id and str(cid) != str(campaign_id):
                continue
            if cid not in by_campaign:
                resolved_name = _resolve_campaign_name(cid, term.get("campaign_name", ""), campaign_name_map)
                by_campaign[cid] = {
                    "campaign_name": resolved_name,
                    "campaign_status": str(term.get("campaign_status") or "ENABLED").upper(),
                    "terms": [],
                }
            by_campaign[cid]["terms"].append(term)

        client = get_gemini_client()
        actions: List[PendingAction] = []
        total_classified = 0

        for cid, camp_data in by_campaign.items():
            camp_status = camp_data.get("campaign_status", "ENABLED")
            # Fetch existing negatives once per campaign for dedup
            try:
                existing_negatives = connector.fetch_campaign_negative_keywords(cid)
                existing_negative_texts = {n["text"].lower() for n in existing_negatives}
            except Exception as e:
                logger.warning(f"Failed to fetch existing negatives for campaign {cid}: {e}")
                existing_negative_texts = set()

            campaign_name = camp_data["campaign_name"]
            terms = camp_data["terms"]

            # Filter to candidates meeting threshold before sending to Gemini
            candidates = []
            for t in terms:
                if t.get("clicks", 0) >= min_clicks or t.get("spend", 0) >= min_spend:
                    term_text = t.get("term", "")
                    if not term_text:
                        continue
                    if term_text.lower() in existing_negative_texts:
                        continue
                    if _already_pending(db, account_id, cid, term_text):
                        continue
                    if _is_suppressed(db, account_id, cid, term_text):
                        continue
                    candidates.append(t)

            if not candidates:
                continue

            # Batch in chunks of 100
            for i in range(0, len(candidates), 100):
                batch = candidates[i:i+100]
                classifications = _classify_search_terms_batch(client, account, campaign_name, cid, batch, db)
                total_classified += len(batch)
                time.sleep(2)  # small delay between Gemini calls

                classification_map = {c.get("search_term", "").lower(): c for c in classifications}

                for term in batch:
                    term_text = term.get("term", "")
                    classification = classification_map.get(term_text.lower())
                    if not classification:
                        continue
                    if classification.get("classification", "").upper() != "IRRELEVANT":
                        continue

                    confidence = (classification.get("confidence") or "MEDIUM").upper()
                    confidence_score = None
                    try:
                        confidence_score = int(classification.get("confidence_score"))
                    except Exception:
                        pass

                    actions.append(PendingAction(
                        account_id=account_id,
                        action_type="SMART_ADD_NEGATIVE_KEYWORD",
                        platform="google",
                        campaign_id=cid,
                        keyword=term_text,
                        match_type="EXACT",
                        reason=f"Search term '{term_text}' classified as irrelevant: {classification.get('reason', '')}. Add as campaign-level exact negative keyword.",
                        new_value={
                            "audit_type": "search_term_audit",
                            "recommendation": "add_negative_keyword",
                            "negative_match_type": "EXACT",
                            "level": "campaign",
                            "campaign_name": campaign_name,
                            "metrics": {
                                "spend": term.get("spend", 0),
                                "clicks": term.get("clicks", 0),
                                "conversions": term.get("conversions", 0),
                                "impressions": term.get("impressions", 0),
                                "ctr": term.get("ctr", 0),
                            },
                            "gemini_reason": classification.get("reason", ""),
                            "confidence": confidence,
                            "confidence_score": confidence_score,
                        },
                        status="pending",
                        campaign_status="ENABLED",
                        confidence=confidence,
                        confidence_score=confidence_score,
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
            "search_terms_classified": total_classified,
            "actions": [a.to_dict() for a in actions],
        }
    except Exception as e:
        logger.error(f"Search term audit failed for account {account_id}: {e}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return {"error": str(e), "account_id": account_id, "actions_generated": 0}
    finally:
        if close_session:
            db.close()
