"""
Recommendation engine for Google Ads optimization.
Analyzes campaigns, search terms, and keywords to suggest actions.
"""
from typing import Dict, Any, List
from backend.services.mock_db import mock_db, NEGATIVE_INTENT_WORDS


def build_audit_summary(campaign_id: str = None) -> Dict[str, Any]:
    """Build a structured audit summary for one or all campaigns."""
    terms = mock_db.get_filtered_search_terms(campaign_id)
    campaigns = mock_db.campaigns
    if campaign_id:
        campaigns = [c for c in campaigns if c["id"] == campaign_id]

    bad_terms = [t for t in terms if t["flags"]]
    total_spend = sum(c["spend"] for c in campaigns)
    total_waste = sum(t["cost"] for t in bad_terms)

    recommendations: List[Dict[str, Any]] = []

    # Negative keyword recommendations
    for t in bad_terms:
        reason = t["flags"][0] if t["flags"] else "Low performance"
        recommendations.append({
            "type": "ADD_NEGATIVE_KEYWORD",
            "campaign_id": t["campaign_id"],
            "campaign_name": t["campaign_name"],
            "keyword": t["term"],
            "match_type": "EXACT",
            "reason": reason,
            "estimated_savings": t["cost"],
        })

    # Budget recommendations
    for c in campaigns:
        if c["conversions"] > 0 and c["cpa"] > c.get("target_cpa", 0) > 0:
            recommendations.append({
                "type": "REDUCE_BUDGET",
                "campaign_id": c["id"],
                "campaign_name": c["name"],
                "reason": f"CPA (${c['cpa']:.2f}) exceeds target (${c['target_cpa']:.2f})",
                "current_budget": c["budget"],
                "suggested_budget": round(c["budget"] * 0.85, 2),
            })
        elif c["conversions"] == 0 and c["spend"] > c["budget"] * 0.7:
            recommendations.append({
                "type": "PAUSE_OR_REDUCE_BUDGET",
                "campaign_id": c["id"],
                "campaign_name": c["name"],
                "reason": f"Zero conversions with high spend (${c['spend']:.2f} / ${c['budget']:.2f})",
                "current_budget": c["budget"],
                "suggested_budget": round(c["budget"] * 0.5, 2),
            })

    # Bid recommendations (mock)
    for t in bad_terms:
        if t["cost"] > 100 and t["conversions"] == 0:
            recommendations.append({
                "type": "REDUCE_BID",
                "campaign_id": t["campaign_id"],
                "campaign_name": t["campaign_name"],
                "keyword": t["term"],
                "reason": "High spend, no conversions; reduce bid or exclude",
                "suggested_bid": 0.5,
            })

    return {
        "campaigns_audited": len(campaigns),
        "total_spend": round(total_spend, 2),
        "estimated_waste": round(total_waste, 2),
        "waste_percentage": round((total_waste / total_spend) * 100, 2) if total_spend else 0.0,
        "problematic_terms": len(bad_terms),
        "recommendations": recommendations,
    }


def suggest_keyword_match_type(term: str) -> str:
    lower = term.lower()
    if any(w in lower for w in NEGATIVE_INTENT_WORDS):
        return "EXACT"
    if len(term.split()) <= 2:
        return "PHRASE"
    return "EXACT"
