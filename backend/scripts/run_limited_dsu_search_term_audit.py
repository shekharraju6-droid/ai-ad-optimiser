"""Run a limited search term audit after Gemini free-tier quota resets.

This script:
1. Makes a tiny test Gemini call to verify quota is available
2. If quota OK, runs search term audit for DSU only
3. Reports confidence breakdown and examples
4. If quota still exhausted, exits cleanly and tells you to wait longer
"""
import json
import logging
from backend.db.database import SessionLocal
from backend.db.models import Account, PendingAction
from backend.services.search_term_auditor import run_search_term_audit
from backend.services.ai_client import get_gemini_client
from backend.routes.audits import _merge_search_term_actions, _fetch_campaign_name_map

logger = logging.getLogger("AdOptima")
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')


def check_gemini_quota() -> bool:
    """Try a minimal Gemini call to see if quota is available."""
    try:
        client = get_gemini_client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents='Return a one-word JSON string: "ok"',
            config={"response_mime_type": "application/json"},
        )
        text = response.text if hasattr(response, "text") else ""
        return bool(text)
    except Exception as e:
        err = str(e).lower()
        if any(code in err for code in ["429", "503", "quota", "unavailable", "resource_exhausted"]):
            logger.warning(f"Gemini quota not yet reset: {e}")
            return False
        logger.error(f"Gemini test call failed: {e}")
        return False


def report_account_negatives(account_id: int) -> dict:
    db = SessionLocal()
    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        actions = db.query(PendingAction).filter(
            PendingAction.account_id == account_id,
            PendingAction.status == "pending",
            PendingAction.action_type == "SMART_ADD_NEGATIVE_KEYWORD",
        ).all()
        if not actions:
            return {"account_name": account.name if account else "?", "total": 0}
        campaign_name_map = _fetch_campaign_name_map(account)
        merged = _merge_search_term_actions(actions, campaign_name_map)
        high = [m for m in merged if (m.get("confidence") or "MEDIUM").upper() == "HIGH"]
        medium = [m for m in merged if (m.get("confidence") or "MEDIUM").upper() == "MEDIUM"]
        low = [m for m in merged if (m.get("confidence") or "MEDIUM").upper() == "LOW"]
        result = {
            "account_name": account.name if account else "?",
            "total": len(merged),
            "high": len(high),
            "medium": len(medium),
            "low": len(low),
            "high_examples": [],
            "landing_page_example": None,
        }
        for m in high[:3]:
            reason = (m.get("findings") or [{}])[0].get("detail", "") if m.get("findings") else ""
            result["high_examples"].append({
                "search_term": m["search_term"],
                "campaign": m["campaign_name"],
                "spend": m.get("spend", 0),
                "clicks": m.get("clicks", 0),
                "confidence": m.get("confidence"),
                "confidence_score": m.get("confidence_score"),
                "reason": reason,
            })
        # Find one example where reason references landing page / business context
        for m in merged:
            reason = (m.get("findings") or [{}])[0].get("detail", "").lower() if m.get("findings") else ""
            if "landing page" in reason or "business context" in reason or "negative rules" in reason:
                result["landing_page_example"] = {
                    "search_term": m["search_term"],
                    "campaign": m["campaign_name"],
                    "confidence": m.get("confidence"),
                    "confidence_score": m.get("confidence_score"),
                    "reason": (m.get("findings") or [{}])[0].get("detail", ""),
                }
                break
        return result
    finally:
        db.close()


def main():
    db = SessionLocal()
    try:
        logger.info("Checking Gemini quota with a tiny test call...")
        if not check_gemini_quota():
            logger.error("Gemini free-tier quota still exhausted. Please wait longer (free tier resets every 24 hours).")
            return

        dsu = db.query(Account).filter(Account.name == "DSU").first()
        if not dsu:
            logger.error("DSU account not found")
            return

        logger.info(f"Running search term audit for DSU (id={dsu.id})...")
        result = run_search_term_audit(dsu.id, db=db)
        logger.info(f"DSU search term audit result: {result}")

        # Refresh report
        report = report_account_negatives(dsu.id)
        logger.info("=" * 60)
        logger.info("DSU NEGATIVE KEYWORD REPORT")
        logger.info("=" * 60)
        logger.info(json.dumps(report, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
