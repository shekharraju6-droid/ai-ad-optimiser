"""
Limited proof-of-concept search term audit for DSU.

Uses exactly 2 Gemini API calls:
- One call for the highest-spend DSU campaign
- One call for the second highest-spend DSU campaign

Each call batches up to 100 search terms by spend.
Includes business context, negative rules, landing page summary, past patterns.
"""
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db.database import SessionLocal
from backend.db.models import Account, PendingAction, CampaignLandingPage, SuppressedSearchTerm
from backend.services.connectors import get_connector
from backend.services.ai_client import get_gemini_client
from backend.services.landing_page_service import get_landing_page_summary
from google.genai import types

logger = logging.getLogger("AdOptima")
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')


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


def _past_patterns(db: Session, account_id: int, campaign_id: str) -> Dict[str, List[str]]:
    """Return past approved/rejected search terms for a campaign in the last 90 days."""
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


def _classify_campaign_terms(
    client,
    account: Account,
    campaign_name: str,
    campaign_id: str,
    terms_with_metrics: List[Dict[str, Any]],
    db: Session,
) -> List[Dict[str, Any]]:
    """Classify up to 100 search terms for one campaign in a single Gemini call."""
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
            lp_summary_text = f"Landing page URL: {lp['url']} (summary not available)"
    except Exception:
        pass

    # Past patterns
    past = _past_patterns(db, account.id, campaign_id)
    past_approved = ", ".join(past["approved"]) if past["approved"] else "None"
    past_rejected = ", ".join(past["rejected"]) if past["rejected"] else "None"

    lines = []
    for t in terms_with_metrics:
        lines.append(
            f"- '{t['term']}' | clicks={t['clicks']} | spend=Rs {t['spend']:.0f} | "
            f"impressions={t['impressions']} | conversions={t['conversions']}"
        )
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

    max_retries = 3
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
                logger.warning(f"Gemini returned non-array for {campaign_name}: {type(parsed)}")
                return []
            return parsed
        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = any(code in err_str for code in ["429", "503", "quota", "unavailable", "resource_exhausted"])
            if is_rate_limit and attempt < max_retries - 1:
                wait = 3
                logger.warning(f"Gemini rate limit for {campaign_name} (attempt {attempt+1}/{max_retries}): {e}. Retrying in {wait}s...")
                time.sleep(wait)
                continue
            logger.error(f"Gemini classification failed for {campaign_name}: {e}", exc_info=True)
            return []


def run_limited_dsu_audit() -> Dict[str, Any]:
    """Run limited 2-campaign search term audit for DSU."""
    db = SessionLocal()
    try:
        account = db.query(Account).filter(Account.name == "DSU").first()
        if not account:
            return {"error": "DSU account not found"}
        if not (account.has_google and account.google_is_live):
            return {"error": "DSU has no live Google Ads connection"}

        connector = get_connector(account, platform="google")
        if not connector or not connector.is_valid:
            return {"error": "Google Ads connector not valid"}

        # Get search terms and aggregate spend per campaign
        search_terms = connector.fetch_search_terms()
        campaign_spend: Dict[str, Dict[str, Any]] = {}
        for term in search_terms:
            cid = term.get("campaign_id")
            if not cid:
                continue
            if cid not in campaign_spend:
                campaign_spend[cid] = {
                    "campaign_name": term.get("campaign_name", ""),
                    "spend": 0,
                    "terms": [],
                }
            campaign_spend[cid]["spend"] += term.get("spend", 0) or 0
            campaign_spend[cid]["terms"].append(term)

        # Pick top 2 campaigns by spend
        top_campaigns = sorted(campaign_spend.items(), key=lambda x: x[1]["spend"], reverse=True)[:2]
        if len(top_campaigns) < 2:
            return {"error": f"Need 2 campaigns, found {len(top_campaigns)}"}

        client = get_gemini_client()
        all_results = []
        campaign_reports = []

        for cid, data in top_campaigns:
            # Sort terms by spend descending, take top 100
            terms = sorted(data["terms"], key=lambda t: t.get("spend", 0) or 0, reverse=True)[:100]
            campaign_name = data["campaign_name"]
            logger.info(f"Auditing campaign: {campaign_name} (id={cid}, spend={data['spend']:,.2f}, terms={len(terms)})")

            classifications = _classify_campaign_terms(client, account, campaign_name, cid, terms, db)
            logger.info(f"  Classifications returned: {len(classifications)}")

            campaign_reports.append({
                "campaign_id": cid,
                "campaign_name": campaign_name,
                "campaign_spend_30d": data["spend"],
                "terms_sent": len(terms),
                "terms_classified": len(classifications),
            })

            classification_map = {c.get("search_term", "").lower(): c for c in classifications}

            for term in terms:
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

                action = PendingAction(
                    account_id=account.id,
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
                )
                db.add(action)
                all_results.append({
                    "search_term": term_text,
                    "campaign_id": cid,
                    "campaign_name": campaign_name,
                    "spend": term.get("spend", 0),
                    "clicks": term.get("clicks", 0),
                    "conversions": term.get("conversions", 0),
                    "confidence": confidence,
                    "confidence_score": confidence_score,
                    "reason": classification.get("reason", ""),
                })

        db.commit()
        return {
            "account": "DSU",
            "campaigns": campaign_reports,
            "actions_created": len(all_results),
            "results": all_results,
        }
    except Exception as e:
        logger.error(f"Limited DSU audit failed: {e}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return {"error": str(e)}
    finally:
        db.close()


if __name__ == "__main__":
    result = run_limited_dsu_audit()
    print(json.dumps(result, indent=2, default=str))
