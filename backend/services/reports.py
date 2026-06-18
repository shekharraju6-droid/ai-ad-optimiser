"""
Reporting and analytics services for AdOptima AI.
"""
from typing import Dict, Any, List
from backend.services.mock_db import mock_db
from backend.services.recommendations import build_audit_summary


def get_savings_report() -> Dict[str, Any]:
    """Estimate savings by comparing current campaign spend to initial spend."""
    initial = mock_db.initial_spend_by_campaign
    current = {c["id"]: c["spend"] for c in mock_db.campaigns}
    total_initial = sum(initial.values())
    total_current = sum(current.values())
    return {
        "initial_spend": round(total_initial, 2),
        "current_spend": round(total_current, 2),
        "estimated_savings": round(max(0, total_initial - total_current), 2),
        "negative_keywords_added": sum(len(n) for n in mock_db.negatives.values()),
    }


def get_waste_breakdown() -> Dict[str, Any]:
    """Break waste down by campaign and reason."""
    terms = mock_db.get_filtered_search_terms()
    bad_terms = [t for t in terms if t["flags"]]

    by_campaign: Dict[str, Dict[str, Any]] = {}
    by_reason: Dict[str, float] = {}

    for t in bad_terms:
        cid = t["campaign_id"]
        cname = t["campaign_name"]
        if cid not in by_campaign:
            by_campaign[cid] = {"name": cname, "waste": 0.0, "terms": 0}
        by_campaign[cid]["waste"] += t["cost"]
        by_campaign[cid]["terms"] += 1
        reason = t["flags"][0]
        by_reason[reason] = by_reason.get(reason, 0.0) + t["cost"]

    return {
        "total_waste": round(sum(v["waste"] for v in by_campaign.values()), 2),
        "by_campaign": [
            {"campaign_id": k, "campaign_name": v["name"], "waste": round(v["waste"], 2), "terms": v["terms"]}
            for k, v in by_campaign.items()
        ],
        "by_reason": [{"reason": k, "waste": round(v, 2)} for k, v in by_reason.items()],
    }


def get_action_history() -> List[Dict[str, Any]]:
    """Return optimization actions taken."""
    return [log for log in mock_db.action_logs if log["type"] in ("OPTIMIZATION", "API_MUTATION")]


def get_full_report() -> Dict[str, Any]:
    return {
        "audit": build_audit_summary(),
        "savings": get_savings_report(),
        "waste_breakdown": get_waste_breakdown(),
        "action_history": get_action_history(),
    }
