from typing import Optional
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from backend.services.config import load_config
from backend.services.google_ads import GoogleAdsApiClient

router = APIRouter(prefix="/api", tags=["campaigns"])

_CAMPAIGN_QUERY = """
    SELECT
      campaign.id,
      campaign.name,
      campaign.status,
      campaign.campaign_budget,
      metrics.cost_micros,
      metrics.clicks,
      metrics.impressions,
      metrics.conversions
    FROM campaign
    WHERE campaign.status = 'ENABLED'
"""


def _format_campaign_row(row):
    cost = (row.get("metrics.cost_micros") or 0) / 1_000_000.0
    clicks = row.get("metrics.clicks") or 0
    impressions = row.get("metrics.impressions") or 0
    conversions = row.get("metrics.conversions") or 0
    ctr = round((clicks / impressions) * 100, 2) if impressions else 0.0
    cpa = round(cost / conversions, 2) if conversions else 0.0
    return {
        "id": str(row.get("campaign.id")),
        "name": row.get("campaign.name", "Unnamed Campaign"),
        "status": str(row.get("campaign.status")),
        "budget": (row.get("campaign.campaign_budget") or 0) / 1_000_000.0,
        "spend": cost,
        "clicks": clicks,
        "impressions": impressions,
        "conversions": conversions,
        "ctr": ctr,
        "cpa": cpa,
    }


@router.get("/campaigns")
def get_campaigns():
    config = load_config()
    client = GoogleAdsApiClient(config)
    if not client.is_valid:
        return JSONResponse(status_code=400, content={"error": "Invalid Google Ads credentials. Please check settings."})

    try:
        rows = client.run_gaql(_CAMPAIGN_QUERY)
        return [_format_campaign_row(r) for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"API Error: {str(e)}"})


@router.get("/campaign/{campaign_id}/details")
def get_campaign_details(campaign_id: str):
    config = load_config()
    client = GoogleAdsApiClient(config)
    if not client.is_valid:
        return JSONResponse(status_code=400, content={"error": "Google Ads client not configured."})

    campaign_query = f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign.campaign_budget,
          metrics.cost_micros,
          metrics.clicks,
          metrics.impressions,
          metrics.conversions
        FROM campaign
        WHERE campaign.id = {campaign_id}
    """
    try:
        campaign_rows = client.run_gaql(campaign_query)
        campaign = _format_campaign_row(campaign_rows[0]) if campaign_rows else None
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"API Error: {str(e)}"})

    if not campaign:
        return JSONResponse(status_code=404, content={"error": "Campaign not found"})

    terms_query = f"""
        SELECT
          search_term_view.search_term,
          metrics.clicks,
          metrics.impressions,
          metrics.cost_micros,
          metrics.conversions
        FROM search_term_view
        WHERE campaign.id = {campaign_id}
          AND segments.date DURING LAST_30_DAYS
    """
    terms = []
    try:
        for row in client.run_gaql(terms_query):
            clicks = row.get("metrics.clicks") or 0
            impressions = row.get("metrics.impressions") or 0
            cost = (row.get("metrics.cost_micros") or 0) / 1_000_000.0
            conversions = row.get("metrics.conversions") or 0
            ctr = round((clicks / impressions) * 100, 2) if impressions else 0.0
            cpa = round(cost / conversions, 2) if conversions else 0.0
            terms.append({
                "term": row.get("search_term_view.search_term"),
                "clicks": clicks,
                "impressions": impressions,
                "cost": round(cost, 2),
                "conversions": conversions,
                "ctr": ctr,
                "cpa": cpa,
                "match_type": "SEARCH_TERM",
                "flags": [],
            })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Search terms API Error: {str(e)}"})

    negatives_query = f"""
        SELECT
          campaign_criterion.criterion_id,
          campaign_criterion.keyword.text,
          campaign_criterion.keyword.match_type
        FROM campaign_criterion
        WHERE campaign_criterion.negative = TRUE
          AND campaign_criterion.type = 'KEYWORD'
          AND campaign.id = {campaign_id}
    """
    negatives = []
    try:
        for row in client.run_gaql(negatives_query):
            negatives.append({
                "id": str(row.get("campaign_criterion.criterion_id")),
                "text": row.get("campaign_criterion.keyword.text"),
                "match_type": str(row.get("campaign_criterion.keyword.match_type")),
            })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Negatives API Error: {str(e)}"})

    return {"campaign": campaign, "search_terms": terms, "negatives": negatives}
