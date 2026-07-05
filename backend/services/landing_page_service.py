"""
Landing page service: fetch URLs from Google Ads, store in campaign_landing_pages,
and crawl content via Gemini for smarter search term audits.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session

from backend.db.database import SessionLocal
from backend.db.models import Account, CampaignLandingPage, PendingAction
from backend.services.connectors import get_connector
from backend.services.ai_client import get_gemini_client
from google.genai import types

logger = logging.getLogger("AdOptima")

CRAWL_INTERVAL_DAYS = 7


def fetch_campaign_landing_pages(account_id: int, db: Session = None) -> Dict[str, Any]:
    """Pull landing page URLs from Google Ads and upsert into campaign_landing_pages.

    Also creates ALERT_MISSING_LANDING_PAGE pending actions for campaigns without URLs.
    Safe: never disrupts existing credentials or audit logic.
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return {"error": "Account not found"}
        if not (account.has_google and account.google_is_live):
            return {"error": "Account has no live Google Ads connection"}

        connector = get_connector(account, platform="google")
        if not connector or not connector.is_valid:
            return {"error": "Google Ads connector not valid"}

        pages = connector.fetch_landing_pages()
        upserted = 0
        missing_alerts = 0

        for p in pages:
            cid = p.get("campaign_id") or ""
            if not cid:
                continue
            url = p.get("landing_page_url")
            cname = p.get("campaign_name") or ""
            existing = db.query(CampaignLandingPage).filter(
                CampaignLandingPage.account_id == account_id,
                CampaignLandingPage.campaign_id == cid,
            ).first()

            if existing:
                if url and existing.landing_page_url != url:
                    existing.landing_page_url = url
                    existing.campaign_name = cname or existing.campaign_name
                    existing.updated_at = datetime.utcnow()
                    # URL changed -> force re-crawl by clearing last_crawled_at
                    existing.last_crawled_at = None
                    existing.landing_page_content = None
                elif cname and not existing.campaign_name:
                    existing.campaign_name = cname
                upserted += 1
            else:
                db.add(CampaignLandingPage(
                    account_id=account_id,
                    campaign_id=cid,
                    campaign_name=cname,
                    landing_page_url=url,
                ))
                upserted += 1

            if not url:
                alert_exists = db.query(PendingAction).filter(
                    PendingAction.account_id == account_id,
                    PendingAction.campaign_id == cid,
                    PendingAction.action_type == "ALERT_MISSING_LANDING_PAGE",
                    PendingAction.status == "pending",
                ).first()
                if not alert_exists:
                    db.add(PendingAction(
                        account_id=account_id,
                        action_type="ALERT_MISSING_LANDING_PAGE",
                        platform="google",
                        campaign_id=cid,
                        reason="Campaign has no landing page URL set. AI audit cannot evaluate search term relevance without knowing what the campaign promotes.",
                        new_value={
                            "campaign_name": cname,
                            "alert_type": "missing_landing_page",
                        },
                        status="pending",
                        campaign_status="ENABLED",
                    ))
                    missing_alerts += 1

        db.commit()
        return {
            "account_id": account_id,
            "campaigns_found": len(pages),
            "upserted": upserted,
            "missing_alerts": missing_alerts,
        }
    except Exception as e:
        logger.error(f"fetch_campaign_landing_pages failed for account {account_id}: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        if close_session:
            db.close()


def get_landing_page_summary(db: Session, account_id: int, campaign_id: str) -> Optional[Dict[str, Any]]:
    """Return the stored landing page summary for a campaign, or None."""
    row = db.query(CampaignLandingPage).filter(
        CampaignLandingPage.account_id == account_id,
        CampaignLandingPage.campaign_id == campaign_id,
    ).first()
    if not row:
        return None
    summary = None
    if row.landing_page_content:
        try:
            summary = json.loads(row.landing_page_content)
        except Exception:
            summary = {"raw": row.landing_page_content}
    return {
        "url": row.landing_page_url,
        "summary": summary,
        "last_crawled_at": row.last_crawled_at.isoformat() if row.last_crawled_at else None,
    }


def crawl_landing_page(url: str) -> Dict[str, Any]:
    """Fetch landing page HTML and send to Gemini for structured summary.

    Returns dict with keys: success (bool), content (str|dict), error (str|None)
    """
    if not url:
        return {"success": False, "error": "No URL provided", "content": None}
    try:
        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        if resp.status_code >= 400:
            return {"success": False, "error": f"HTTP {resp.status_code}", "content": None}
        html_text = resp.text or ""
        if not html_text.strip():
            return {"success": False, "error": "Empty page content", "content": None}
    except Exception as e:
        return {"success": False, "error": f"Fetch failed: {e}", "content": None}

    client = get_gemini_client()
    if not client:
        return {"success": False, "error": "Gemini client not available", "content": html_text[:2000]}

    prompt = f"""You are analysing a landing page for a digital advertising campaign. Extract and summarise the following information from this page content. Return ONLY a valid JSON object:

{{
  "business_name": "company or institution name",
  "product_or_service": "what they are selling or promoting (e.g. BBA degree program, real estate project, healthcare service)",
  "target_audience": "who this is for (e.g. students seeking undergraduate admission, home buyers in Bangalore)",
  "location": "geographic focus if any",
  "price_range": "pricing if mentioned",
  "key_features": ["list of main selling points"],
  "what_they_do_NOT_offer": ["things clearly not offered based on the page content"],
  "competitors_mentioned": ["any competitor names"],
  "call_to_action": "what the page wants visitors to do (apply now, book a visit, call us)",
  "summary": "2-3 sentence plain English summary of what this landing page is about"
}}

Page content:
{html_text[:8000]}
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                system_instruction="You are a precise landing page analyser. Return only valid JSON. Never include explanations outside the JSON object.",
            ),
        )
        text = response.text if hasattr(response, "text") else ""
        parsed = json.loads(text)
        return {"success": True, "content": parsed, "error": None}
    except Exception as e:
        logger.warning(f"Gemini landing page parse failed for {url}: {e}")
        return {"success": False, "error": f"Gemini parse failed: {e}", "content": html_text[:2000]}


def crawl_stale_landing_pages(account_id: int, db: Session = None) -> Dict[str, Any]:
    """Re-crawl landing pages where last_crawled_at is older than 7 days or URL changed.

    Skips campaigns with no URL. Non-blocking: failures are logged, not raised.
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    try:
        threshold = datetime.utcnow() - timedelta(days=CRAWL_INTERVAL_DAYS)
        rows = db.query(CampaignLandingPage).filter(
            CampaignLandingPage.account_id == account_id,
            CampaignLandingPage.landing_page_url.isnot(None),
        ).all()
        crawled = 0
        skipped = 0
        for row in rows:
            if row.last_crawled_at and row.last_crawled_at > threshold:
                skipped += 1
                continue
            result = crawl_landing_page(row.landing_page_url)
            if result.get("success") and result.get("content"):
                row.landing_page_content = json.dumps(result["content"], ensure_ascii=False)
            elif result.get("content"):
                row.landing_page_content = json.dumps({"raw": str(result["content"])[:2000]}, ensure_ascii=False)
            else:
                row.landing_page_content = None
            row.last_crawled_at = datetime.utcnow()
            row.updated_at = datetime.utcnow()
            crawled += 1
        db.commit()
        return {"account_id": account_id, "crawled": crawled, "skipped_fresh": skipped}
    except Exception as e:
        logger.error(f"crawl_stale_landing_pages failed for account {account_id}: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        if close_session:
            db.close()