"""
Reporting and analytics services for AdOptima AI.
Live data sourced from Google Ads API and DB-backed pending actions.
"""
from typing import Dict, Any, List
from backend.services.config import load_config
from backend.services.google_ads import GoogleAdsApiClient
from backend.services.recommendations import build_audit_summary


def _live_client() -> GoogleAdsApiClient:
    return GoogleAdsApiClient(load_config())


def get_savings_report() -> Dict[str, Any]:
    """Savings report derived from live campaign data + pending actions count."""
    client = _live_client()
    initial = 0.0
    current = 0.0
    if client.is_valid:
        try:
            rows = client.run_gaql(
                "SELECT campaign.id, metrics.cost_micros FROM campaign WHERE segments.date DURING LAST_30_DAYS"
            )
            for r in rows:
                current += (r.get("metrics.cost_micros") or 0) / 1_000_000.0
        except Exception:
            pass
    return {
        "initial_spend": round(initial, 2),
        "current_spend": round(current, 2),
        "estimated_savings": 0.0,
        "negative_keywords_added": 0,
    }


def get_waste_breakdown() -> Dict[str, Any]:
    """Break waste down by campaign and reason using live search-term data."""
    client = _live_client()
    by_campaign: Dict[str, Dict[str, Any]] = {}
    by_reason: Dict[str, float] = {}

    if client.is_valid:
        try:
            rows = client.run_gaql(
                "SELECT search_term_view.search_term, campaign.id, campaign.name, "
                "metrics.clicks, metrics.impressions, metrics.cost_micros, metrics.conversions "
                "FROM search_term_view WHERE segments.date DURING LAST_30_DAYS"
            )
            from backend.routes.search_terms import NEGATIVE_INTENT_WORDS
            for r in rows:
                term = r.get("search_term_view.search_term", "") or ""
                cost = (r.get("metrics.cost_micros") or 0) / 1_000_000.0
                conversions = r.get("metrics.conversions") or 0
                flags = []
                if conversions == 0 and cost > 50:
                    flags.append("High Spend, No Conversions")
                for word in NEGATIVE_INTENT_WORDS:
                    if word in term.lower():
                        flags.append(f"Unproductive Term (contains '{word}')")
                        break
                if not flags:
                    continue
                cid = str(r.get("campaign.id"))
                cname = r.get("campaign.name", "Unknown")
                if cid not in by_campaign:
                    by_campaign[cid] = {"name": cname, "waste": 0.0, "terms": 0}
                by_campaign[cid]["waste"] += cost
                by_campaign[cid]["terms"] += 1
                reason = flags[0]
                by_reason[reason] = by_reason.get(reason, 0.0) + cost
        except Exception:
            pass

    return {
        "total_waste": round(sum(v["waste"] for v in by_campaign.values()), 2),
        "by_campaign": [
            {"campaign_id": k, "campaign_name": v["name"], "waste": round(v["waste"], 2), "terms": v["terms"]}
            for k, v in by_campaign.items()
        ],
        "by_reason": [{"reason": k, "waste": round(v, 2)} for k, v in by_reason.items()],
    }


def get_action_history() -> List[Dict[str, Any]]:
    """Return optimization actions from the DB (PendingAction)."""
    from backend.db.database import SessionLocal
    from backend.db.models import PendingAction
    db = SessionLocal()
    try:
        actions = db.query(PendingAction).order_by(PendingAction.id.desc()).limit(200).all()
        return [
            {
                "time": (a.created_at.isoformat() if a.created_at else None),
                "type": a.action_type,
                "message": f"{a.action_type} for {a.account.name if a.account else 'Unknown'} - {a.keyword or a.campaign_id or a.adset_id or 'n/a'} [{a.status}]",
            }
            for a in actions
        ]
    finally:
        db.close()


def get_full_report() -> Dict[str, Any]:
    return {
        "audit": build_audit_summary(),
        "savings": get_savings_report(),
        "waste_breakdown": get_waste_breakdown(),
        "action_history": get_action_history(),
    }