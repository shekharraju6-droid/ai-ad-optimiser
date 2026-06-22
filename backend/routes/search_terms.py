from typing import Optional
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from backend.services.config import load_config
from backend.services.google_ads import GoogleAdsApiClient

router = APIRouter(prefix="/api", tags=["search-terms"])

NEGATIVE_INTENT_WORDS = [
    "free", "job", "jobs", "salary", "download", "tutorial", "tutorials",
    "crack", "what is", "how to", "definition", "ppt", "pdf", "question paper",
    "question papers", "time table", "syllabus", "notes"
]

_SEARCH_TERM_QUERY = """
    SELECT
      search_term_view.search_term,
      campaign.name,
      campaign.id,
      metrics.clicks,
      metrics.impressions,
      metrics.cost_micros,
      metrics.conversions
    FROM search_term_view
    WHERE segments.date DURING LAST_30_DAYS
"""


def _format_search_term_row(row):
    term = row.get("search_term_view.search_term", "")
    clicks = row.get("metrics.clicks") or 0
    impressions = row.get("metrics.impressions") or 0
    cost = (row.get("metrics.cost_micros") or 0) / 1_000_000.0
    conversions = row.get("metrics.conversions") or 0
    ctr = round((clicks / impressions) * 100, 2) if impressions else 0.0
    cpa = round(cost / conversions, 2) if conversions else 0.0
    flags = []
    if conversions == 0 and cost > 50:
        flags.append("High Spend, No Conversions")
    if ctr < 1.5:
        flags.append("Low CTR (Poor Relevance)")
    for word in NEGATIVE_INTENT_WORDS:
        if word in term.lower():
            flags.append(f"Unproductive Term (contains '{word}')")
            break
    return {
        "campaign_id": str(row.get("campaign.id")),
        "campaign_name": row.get("campaign.name", "Unknown"),
        "term": term,
        "clicks": clicks,
        "impressions": impressions,
        "cost": round(cost, 2),
        "conversions": conversions,
        "ctr": ctr,
        "cpa": cpa,
        "match_type": "SEARCH_TERM",
        "flags": flags,
    }


@router.get("/search-terms")
def get_search_terms(campaign_id: Optional[str] = None):
    config = load_config()
    client = GoogleAdsApiClient(config)
    if not client.is_valid:
        return JSONResponse(status_code=400, content={"error": "Google Ads API credentials not configured."})

    query = _SEARCH_TERM_QUERY
    if campaign_id:
        query += f" AND campaign.id = {campaign_id}"

    try:
        rows = client.run_gaql(query)
        return [_format_search_term_row(r) for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"API Error: {str(e)}"})
