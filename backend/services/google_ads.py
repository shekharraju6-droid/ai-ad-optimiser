"""
Google Ads API client wrapper with safe read-only mode.
"""
from typing import Dict, Any, List
from fastapi import HTTPException
from backend.services.config import load_config
import logging

logger = logging.getLogger("AdOptima")


class GoogleAdsApiClient:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.client = None
        self.is_valid = False

        if not config.get("developer_token"):
            logger.warning("Developer token missing; cannot initialize live Google Ads client.")
            return

        try:
            from google.ads.googleads.client import GoogleAdsClient
            credentials = {
                "developer_token": config["developer_token"],
                "client_id": config.get("client_id", ""),
                "client_secret": config.get("client_secret", ""),
                "refresh_token": config.get("refresh_token", ""),
                "use_proto_plus": True,
            }
            if config.get("login_customer_id"):
                credentials["login_customer_id"] = config["login_customer_id"]

            self.client = GoogleAdsClient.load_from_dict(credentials)
            self.is_valid = True
            logger.info("Google Ads API client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Google Ads Client: {e}")
            self.is_valid = False

    def _customer_id(self) -> str:
        cid = self.config.get("customer_id", "").replace("-", "").strip()
        if not cid:
            raise HTTPException(status_code=400, detail="Customer ID is required for live API calls.")
        return cid

    def run_gaql(self, query: str) -> List[Dict[str, Any]]:
        if not self.is_valid or not self.client:
            raise HTTPException(status_code=400, detail="Google Ads client not configured.")

        customer_id = self._customer_id()
        try:
            service = self.client.get_service("GoogleAdsService")
            response = service.search(customer_id=customer_id, query=query)
            results = []
            for row in response:
                row_dict = {}
                for field in response.metadata.field_mask.paths:
                    parts = field.split(".")
                    val = row
                    for part in parts:
                        val = getattr(val, part, None)
                    row_dict[field] = val
                results.append(row_dict)
            return results
        except Exception as e:
            logger.error(f"GAQL query failed: {e}")
            raise HTTPException(status_code=500, detail=f"Google Ads API Error: {str(e)}")

    def mutate_campaign_budget(self, campaign_id: str, new_budget: float) -> Dict[str, Any]:
        if not self.is_valid or not self.client:
            raise HTTPException(status_code=400, detail="Google Ads client not configured.")

        if self.config.get("safe_mode", True):
            raise HTTPException(status_code=403, detail="Safe mode is enabled. Disable safe mode to apply mutations.")

        customer_id = self._customer_id()
        try:
            campaign_service = self.client.get_service("CampaignService")
            campaign_operation = self.client.get_type("CampaignOperation")
            campaign = campaign_operation.update
            campaign.resource_name = campaign_service.campaign_path(customer_id, campaign_id)
            campaign.campaign_budget = new_budget * 1_000_000  # micros
            self.client.copy_from(campaign_operation.update_mask, self.client.field_mask("campaign.campaign_budget"))

            response = campaign_service.mutate_campaigns(customer_id=customer_id, operations=[campaign_operation])
            logger.info(f"Budget updated for campaign {campaign_id} to {new_budget}")
            return {"success": True, "campaign_id": campaign_id, "new_budget": new_budget, "resource": response.results[0].resource_name}
        except Exception as e:
            logger.error(f"Failed to update campaign budget: {e}")
            raise HTTPException(status_code=500, detail=f"Google Ads Mutation Failed: {str(e)}")

    def mutate_ad_group_criterion_bid(self, ad_group_id: str, criterion_id: str, new_bid: float) -> Dict[str, Any]:
        if not self.is_valid or not self.client:
            raise HTTPException(status_code=400, detail="Google Ads client not configured.")

        if self.config.get("safe_mode", True):
            raise HTTPException(status_code=403, detail="Safe mode is enabled. Disable safe mode to apply mutations.")

        customer_id = self._customer_id()
        try:
            agc_service = self.client.get_service("AdGroupCriterionService")
            operation = self.client.get_type("AdGroupCriterionOperation")
            criterion = operation.update
            criterion.resource_name = agc_service.ad_group_criterion_path(customer_id, ad_group_id, criterion_id)
            criterion.cpc_bid_micros = int(new_bid * 1_000_000)
            self.client.copy_from(operation.update_mask, self.client.field_mask("ad_group_criterion.cpc_bid_micros"))

            response = agc_service.mutate_ad_group_criteria(customer_id=customer_id, operations=[operation])
            logger.info(f"Bid updated for criterion {criterion_id} to {new_bid}")
            return {"success": True, "criterion_id": criterion_id, "new_bid": new_bid, "resource": response.results[0].resource_name}
        except Exception as e:
            logger.error(f"Failed to update keyword bid: {e}")
            raise HTTPException(status_code=500, detail=f"Google Ads Mutation Failed: {str(e)}")

    def add_negative_keyword(self, campaign_id: str, keyword: str, match_type: str = "EXACT") -> Dict[str, Any]:
        if not self.is_valid or not self.client:
            raise HTTPException(status_code=400, detail="Google Ads client not configured.")

        if self.config.get("safe_mode", True):
            raise HTTPException(status_code=403, detail="Safe mode is enabled. Disable safe mode to apply mutations.")

        customer_id = self._customer_id()
        try:
            cc_service = self.client.get_service("CampaignCriterionService")
            operation = self.client.get_type("CampaignCriterionOperation")
            criterion = operation.create
            criterion.campaign = self.client.get_service("CampaignService").campaign_path(customer_id, campaign_id)
            criterion.negative = True
            criterion.type_ = self.client.enums.CriterionTypeEnum.KEYWORD
            criterion.keyword.text = keyword

            enum_val = getattr(self.client.enums.KeywordMatchTypeEnum, match_type, None)
            criterion.keyword.match_type = enum_val if enum_val else self.client.enums.KeywordMatchTypeEnum.EXACT

            response = cc_service.mutate_campaign_criteria(customer_id=customer_id, operations=[operation])
            created_resource = response.results[0].resource_name
            criterion_id = created_resource.split("~")[-1]
            logger.info(f"Negative keyword added: {keyword} ({match_type}) on campaign {campaign_id}")
            return {"success": True, "negative": {"id": criterion_id, "text": keyword, "match_type": match_type, "campaign_id": campaign_id}}
        except Exception as e:
            logger.error(f"Failed to add negative keyword: {e}")
            raise HTTPException(status_code=500, detail=f"Google Ads Mutation Failed: {str(e)}")


def get_client() -> GoogleAdsApiClient:
    return GoogleAdsApiClient(load_config())
