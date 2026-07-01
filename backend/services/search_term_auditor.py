"""
Smart Search Term Auditor for Google Ads.

Uses Gemini to classify search terms as RELEVANT or IRRELEVANT per campaign,
then creates PendingAction recommendations to add EXACT negative keywords
at the campaign level. No auto-application.
"""
import json
import logging
import time
from datetime import datetime, date
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session

from backend.db.database import SessionLocal
from backend.db.models import Account, CampaignTypeTag, PendingAction, SuppressedSearchTerm
from backend.services.ai_client import get_gemini_client
from backend.services.connectors import get_connector
from backend.services.audit_settings import get_int_setting
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


def _already_pending(db: Session, account_id: int, campaign_id: str, term: str) -> bool:
    existing = db.query(PendingAction).filter(
        PendingAction.account_id == account_id,
        PendingAction.campaign_id == campaign_id,
        PendingAction.keyword == term,
        PendingAction.action_type == "SMART_ADD_NEGATIVE_KEYWORD",
        PendingAction.status == "pending",
    ).first()
    return existing is not None


def _classify_search_terms_batch(client, account: Account, campaign_name: str, terms_with_metrics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Send up to 100 search terms to Gemini and return classifications."""
    if not terms_with_metrics:
        return []

    brand_terms = _brand_terms_for_account(account)
    client_name = account.name or "the client"
    category = account.group.name if account.group else "general"

    lines = []
    for t in terms_with_metrics:
        lines.append(f"- '{t['term']}' | clicks={t['clicks']} | spend=Rs {t['spend']:.0f} | impressions={t['impressions']} | conversions={t['conversions']}")
    terms_block = "\n".join(lines)

    prompt = f"""You are a Google Ads search term auditor for the company: {client_name}
Industry/Category: {category}
Brand terms: {brand_terms}
Campaign name: {campaign_name}

Below is a list of search terms that triggered ads for this campaign in the last 30 days. For each search term, classify it as either RELEVANT or IRRELEVANT.

A search term is IRRELEVANT if:
- It has no logical connection to the client's business or the campaign's intent
- It contains "free", "salary", "jobs", "career", "recruitment" (unless the client is in recruitment)
- It is about a competitor by name
- It is geographically irrelevant
- It is seeking information that the client does not offer
- It is clearly a different intent (e.g., someone searching for downloads, torrents, reviews of something unrelated)

A search term is RELEVANT if:
- It relates to the client's products, services, or industry
- It shows purchase/enquiry intent aligned with the campaign

Return ONLY a valid JSON array with this format:
[
  {{
    "search_term": "the exact search term",
    "classification": "RELEVANT" or "IRRELEVANT",
    "reason": "brief reason for classification"
  }}
]

Search terms to classify:
{terms_block}
"""

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
        logger.error(f"Gemini search term classification failed for campaign '{campaign_name}': {e}", exc_info=True)
        return []


def run_search_term_audit(account_id: int, db: Session = None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    """Run search term audit for a single Google Ads account."""
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

        tags = db.query(CampaignTypeTag).filter(CampaignTypeTag.account_id == account_id).all()
        tags_map = {t.campaign_id: t.campaign_type for t in tags}

        # Thresholds from settings
        min_clicks = get_int_setting("smart_audit_search_term_min_clicks", db)
        min_spend = get_int_setting("smart_audit_search_term_min_spend_inr", db)

        search_terms = connector.fetch_search_terms()

        # Group by campaign
        by_campaign: Dict[str, Dict[str, Any]] = {}
        for term in search_terms:
            cid = term.get("campaign_id")
            if not cid:
                continue
            if cid not in by_campaign:
                by_campaign[cid] = {
                    "campaign_name": term.get("campaign_name", ""),
                    "terms": [],
                }
            by_campaign[cid]["terms"].append(term)

        client = get_gemini_client()
        actions: List[PendingAction] = []
        total_classified = 0

        for cid, camp_data in by_campaign.items():
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
                classifications = _classify_search_terms_batch(client, account, campaign_name, batch)
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
                        },
                        status="pending",
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
        return {"error": str(e), "account_id": account_id, "actions_generated": 0}
    finally:
        if close_session:
            db.close()
