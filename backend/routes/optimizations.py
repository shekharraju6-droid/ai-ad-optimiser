from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from backend.services.config import load_config
from backend.services.google_ads import GoogleAdsApiClient
from backend.services.recommendations import build_audit_summary

router = APIRouter(prefix="/api", tags=["optimizations"])


class BudgetUpdateRequest(BaseModel):
    campaign_id: str
    new_budget: float


class BidUpdateRequest(BaseModel):
    campaign_id: str
    ad_group_id: str
    criterion_id: str
    new_bid: float


@router.get("/audit")
def audit_campaigns(campaign_id: Optional[str] = None):
    return build_audit_summary(campaign_id)


@router.post("/campaign/{campaign_id}/budget")
def update_campaign_budget(campaign_id: str, req: BudgetUpdateRequest):
    config = load_config()
    client = GoogleAdsApiClient(config)
    if not client.is_valid:
        raise HTTPException(status_code=400, detail="Google Ads API client not configured.")
    return client.mutate_campaign_budget(req.campaign_id, req.new_budget)


@router.post("/keyword/bid")
def update_keyword_bid(req: BidUpdateRequest):
    config = load_config()
    client = GoogleAdsApiClient(config)
    if not client.is_valid:
        raise HTTPException(status_code=400, detail="Google Ads API client not configured.")
    return client.mutate_ad_group_criterion_bid(req.ad_group_id, req.criterion_id, req.new_bid)
