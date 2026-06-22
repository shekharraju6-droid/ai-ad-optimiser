from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from backend.services.config import load_config
from backend.services.google_ads import GoogleAdsApiClient

router = APIRouter(prefix="/api", tags=["negatives"])


class AddNegativeRequest(BaseModel):
    campaign_id: str
    keyword: str
    match_type: str = "EXACT"


@router.get("/negative-keywords")
def get_negative_keywords(campaign_id: Optional[str] = None):
    config = load_config()
    client = GoogleAdsApiClient(config)
    if not client.is_valid:
        return JSONResponse(status_code=400, content={"error": "Google Ads API credentials not configured."})

    query = """
        SELECT
          campaign_criterion.criterion_id,
          campaign_criterion.keyword.text,
          campaign_criterion.keyword.match_type,
          campaign.id,
          campaign.name
        FROM campaign_criterion
        WHERE campaign_criterion.negative = TRUE
          AND campaign_criterion.type = 'KEYWORD'
    """
    if campaign_id:
        query += f" AND campaign.id = {campaign_id}"

    try:
        rows = client.run_gaql(query)
        return [
            {
                "id": str(r.get("campaign_criterion.criterion_id")),
                "text": r.get("campaign_criterion.keyword.text"),
                "match_type": str(r.get("campaign_criterion.keyword.match_type")),
                "campaign_id": str(r.get("campaign.id")),
                "campaign_name": r.get("campaign.name"),
            }
            for r in rows
        ]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"API Error: {str(e)}"})


@router.post("/negative-keywords")
def add_negative_keyword(req: AddNegativeRequest):
    config = load_config()
    client = GoogleAdsApiClient(config)
    if not client.is_valid:
        raise HTTPException(status_code=400, detail="Google Ads API client not configured.")

    try:
        return client.add_negative_keyword(req.campaign_id, req.keyword, req.match_type)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google Ads Mutation Failed: {str(e)}")
