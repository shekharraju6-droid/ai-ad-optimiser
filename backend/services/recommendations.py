"""
Recommendation engine for Google Ads optimization.
Analyzes live campaigns, search terms to suggest actions.
"""
from typing import Dict, Any, List
from backend.services.config import load_config
from backend.services.google_ads import GoogleAdsApiClient

NEGATIVE_INTENT_WORDS = [
    "free", "job", "jobs", "salary", "download", "tutorial", "tutorials",
    "crack", "what is", "how to", "definition", "ppt", "pdf", "question paper",
    "question papers", "time table", "syllabus", "notes",
]


def _live_client() -> GoogleAdsApiClient:
    return GoogleAdsApiClient(load_config())


def build_audit_summary(campaign_id: str = None) -> Dict[str, Any]:
    """Build a structured audit summary from live Google Ads data."""
    client = _live_client()
    campaigns = []
    terms = []
    if client.is_valid:
        try:
            camp_query = (
                "SELECT campaign.id, campaign.name, campaign.status, campaign.campaign_budget, "
                "metrics.cost_micros, metrics.clicks, metrics.impressions, metrics.conversions "
                "FROM campaign WHERE campaign.status = 'ENABLED'"
            )
            if campaign_id:
                camp_query += f" AND campaign.id = {campaign_id}"
            for r in client.run_gaql(camp_query):
                cost = (r.get("metrics.cost_micros") or 0) / 1_000_000.0
                clicks = r.get("metrics.clicks") or 0
                impressions = r.get("metrics.impressions") or 0
                conversions = r.get("metrics.conversions") or 0
                campaigns.append({
                    "id": str(r.get("campaign.id")),
                    "name": r.get("campaign.name", "Unnamed"),
                    "spend": cost,
                    "clicks": clicks,
                    "impressions": impressions,
                    "conversions": conversions,
                    "budget": (r.get("campaign.campaign_budget") or 0) / 1_000_000.0,
                    "cpa": round(cost / conversions, 2) if conversions else 0.0,
                    "target_cpa": 0,
                })
        except Exception:
            pass
        try:
            term_query = (
                "SELECT search_term_view.search_term, campaign.id, campaign.name, "
                "metrics.clicks, metrics.impressions, metrics.cost_micros, metrics.conversions "
                "FROM search_term_view WHERE segments.date DURING LAST_30_DAYS"
            )
            if campaign_id:
                term_query += f" AND campaign.id = {campaign_id}"
            for r in client.run_gaql(term_query):
                cost = (r.get("metrics.cost_micros") or 0) / 1_000_000.0
                clicks = r.get("metrics.clicks") or 0
                impressions = r.get("metrics.impressions") or 0
                conversions = r.get("metrics.conversions") or 0
                term_text = r.get("search_term_view.search_term", "") or ""
                flags = []
                if conversions == 0 and cost > 50:
                    flags.append("High Spend, No Conversions")
                ctr = (clicks / impressions * 100) if impressions else 0.0
                if ctr < 1.5:
                    flags.append("Low CTR (Poor Relevance)")
                for word in NEGATIVE_INTENT_WORDS:
                    if word in term_text.lower():
                        flags.append(f"Unproductive Term (contains '{word}')")
                        break
                terms.append({
                    "campaign_id": str(r.get("campaign.id")),
                    "campaign_name": r.get("campaign.name", "Unknown"),
                    "term": term_text,
                    "clicks": clicks,
                    "impressions": impressions,
                    "cost": round(cost, 2),
                    "conversions": conversions,
                    "ctr": round(ctr, 2),
                    "flags": flags,
                })
        except Exception:
            pass

    bad_terms = [t for t in terms if t["flags"]]
    total_spend = sum(c["spend"] for c in campaigns)
    total_waste = sum(t["cost"] for t in bad_terms)

    recommendations: List[Dict[str, Any]] = []

    for t in bad_terms:
        reason = t["flags"][0]
        recommendations.append({
            "type": "ADD_NEGATIVE_KEYWORD",
            "campaign_id": t["campaign_id"],
            "campaign_name": t["campaign_name"],
            "keyword": t["term"],
            "match_type": "EXACT",
            "reason": reason,
            "estimated_savings": t["cost"],
        })

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