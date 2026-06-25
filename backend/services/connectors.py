"""
Platform connector factory for Google Ads and Meta Marketing API.
"""
from typing import Dict, Any, List, Optional
from backend.db.models import Account, AccountType
from backend.services.crypto import decrypt
import logging

logger = logging.getLogger("AdOptima")


class AdsConnector:
    """Base class for ad platform connectors."""
    def __init__(self, account: Account, start_date: Optional[str] = None, end_date: Optional[str] = None):
        self.account = account
        self.start_date = start_date
        self.end_date = end_date
        self.is_valid = False

    def validate_credentials(self) -> bool:
        return False

    def fetch_account_metrics(self) -> Dict[str, Any]:
        raise NotImplementedError

    def fetch_campaigns(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def fetch_search_terms(self, campaign_id: Optional[str] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def apply_negative_keyword(self, campaign_id: str, keyword: str, match_type: str) -> Dict[str, Any]:
        raise NotImplementedError

    def update_campaign_budget(self, campaign_id: str, new_budget: float) -> Dict[str, Any]:
        raise NotImplementedError

    def fetch_billing(self) -> Dict[str, Any]:
        """Fetch billing/balance data. Override in subclasses.

        Returns dict with keys:
          billing_type: "prepaid" | "postpaid" | "unknown"
          amount: float | None  (balance for prepaid, used for postpaid)
          status: "available" | "unavailable"
        """
        return {"billing_type": "unknown", "amount": None, "status": "unavailable"}


class GoogleAdsConnector(AdsConnector):
    def __init__(self, account: Account, start_date: Optional[str] = None, end_date: Optional[str] = None):
        super().__init__(account, start_date=start_date, end_date=end_date)
        self.client = None
        self.validate_credentials()

    def validate_credentials(self) -> bool:
        try:
            from google.ads.googleads.client import GoogleAdsClient
            creds = self._parse_credentials()
            if not creds:
                return False
            self.client = GoogleAdsClient.load_from_dict(creds)
            self.is_valid = True
            return True
        except Exception as e:
            logger.error(f"Google Ads connector failed for account {self.account.id}: {e}")
            self.is_valid = False
            return False

    def _parse_credentials(self) -> Optional[Dict[str, Any]]:
        raw = self.account.google_credentials or self.account.credentials
        if not raw:
            return None
        try:
            import json
            creds = json.loads(decrypt(raw))
            login_customer_id = creds.get("login_customer_id", "")
            result = {
                "developer_token": creds.get("developer_token", ""),
                "client_id": creds.get("client_id", ""),
                "client_secret": creds.get("client_secret", ""),
                "refresh_token": creds.get("refresh_token", ""),
                "use_proto_plus": True,
            }
            if login_customer_id and str(login_customer_id).strip():
                result["login_customer_id"] = str(login_customer_id).replace("-", "")
            return result
        except Exception as e:
            logger.error(f"Failed to parse Google credentials: {e}")
            return None

    def _date_clause(self) -> str:
        if self.start_date and self.end_date:
            return f"segments.date BETWEEN '{self.start_date}' AND '{self.end_date}'"
        return "segments.date DURING LAST_30_DAYS"

    def fetch_account_metrics(self) -> Dict[str, Any]:
        if not self.is_valid:
            return {"error": "Google Ads client not valid"}
        customer_id = (self.account.google_external_id or self.account.external_id or "").replace("-", "")
        if not customer_id:
            return {"error": "No Google customer ID configured"}
        date_clause = self._date_clause()
        query = f"""
            SELECT
              metrics.cost_micros,
              metrics.clicks,
              metrics.impressions,
              metrics.conversions
            FROM customer
            WHERE {date_clause}
        """
        try:
            service = self.client.get_service("GoogleAdsService")
            response = service.search(customer_id=customer_id, query=query)
            total_cost = 0
            total_clicks = 0
            total_impressions = 0
            total_conversions = 0
            for row in response:
                total_cost += row.metrics.cost_micros or 0
                total_clicks += row.metrics.clicks or 0
                total_impressions += row.metrics.impressions or 0
                total_conversions += row.metrics.conversions or 0
            return {
                "spend": round(total_cost / 1_000_000.0, 2),
                "clicks": total_clicks,
                "impressions": total_impressions,
                "conversions": total_conversions,
            }
        except Exception as e:
            logger.error(f"Google fetch metrics failed: {e}")
            return {"error": str(e)}

    def fetch_campaigns(self) -> List[Dict[str, Any]]:
        if not self.is_valid:
            return []
        customer_id = (self.account.google_external_id or self.account.external_id or "").replace("-", "")
        if not customer_id:
            return []
        date_clause = self._date_clause()
        query = f"""
            SELECT
              campaign.id,
              campaign.name,
              campaign.status,
              campaign_budget.amount_micros,
              metrics.cost_micros,
              metrics.clicks,
              metrics.impressions,
              metrics.conversions
            FROM campaign
            WHERE {date_clause}
        """
        try:
            service = self.client.get_service("GoogleAdsService")
            response = service.search(customer_id=customer_id, query=query)
            results = []
            for row in response:
                cost = (row.metrics.cost_micros or 0) / 1_000_000.0
                clicks = row.metrics.clicks or 0
                impressions = row.metrics.impressions or 0
                conversions = row.metrics.conversions or 0
                ctr = round((clicks / impressions) * 100, 2) if impressions else 0.0
                cpa = round(cost / conversions, 2) if conversions else 0.0
                results.append({
                    "id": str(row.campaign.id),
                    "name": row.campaign.name,
                    "status": str(row.campaign.status),
                    "budget": (row.campaign_budget.amount_micros or 0) / 1_000_000.0,
                    "spend": cost,
                    "clicks": clicks,
                    "impressions": impressions,
                    "conversions": conversions,
                    "ctr": ctr,
                    "cpa": cpa,
                })
            return results
        except Exception as e:
            logger.error(f"Google fetch campaigns failed: {e}")
            return []

    def fetch_billing(self) -> Dict[str, Any]:
        """Fetch billing/balance data from Google Ads API.

        Queries account_budget for the spending limit (total budget) and
        calculates available balance = adjusted_spending_limit - spend_since_budget_start.

        Falls back to 'unknown' if the API call fails.
        """
        if not self.is_valid:
            return {"billing_type": "unknown", "amount": None, "status": "unavailable"}
        customer_id = (self.account.google_external_id or self.account.external_id or "").replace("-", "")
        if not customer_id:
            return {"billing_type": "unknown", "amount": None, "status": "unavailable"}
        try:
            service = self.client.get_service("GoogleAdsService")

            # Step 1: Fetch active account_budget to get spending limit and start date
            query_ab = """
                SELECT
                  account_budget.id,
                  account_budget.status,
                  account_budget.approved_spending_limit_micros,
                  account_budget.adjusted_spending_limit_micros,
                  account_budget.approved_start_date_time
                FROM account_budget
            """
            response_ab = service.search(customer_id=customer_id, query=query_ab)
            active_budget = None
            for row in response_ab:
                ab = row.account_budget
                # status 3 = ACTIVE in v24 enum
                if str(ab.status).endswith("3") or str(ab.status) == "AccountBudgetStatus.ACTIVE" or ab.status == 3:
                    active_budget = ab
                    break
                if active_budget is None:
                    active_budget = ab  # fallback to first row

            if not active_budget or not active_budget.adjusted_spending_limit_micros:
                return {"billing_type": "unknown", "amount": None, "status": "unavailable"}

            total_budget = active_budget.adjusted_spending_limit_micros / 1_000_000.0
            budget_start = active_budget.approved_start_date_time or ""

            # Step 2: Fetch spend since budget start date
            # Parse start date: "2026-04-02 09:36:11" → "2026-04-02"
            spend_start = budget_start[:10] if budget_start else "2026-01-01"
            query_spend = f"""
                SELECT
                  metrics.cost_micros
                FROM customer
                WHERE segments.date BETWEEN '{spend_start}' AND '{self.end_date or self.start_date or 'today'}'
            """
            try:
                response_spend = service.search(customer_id=customer_id, query=query_spend)
                total_spend = 0.0
                for row in response_spend:
                    total_spend += (row.metrics.cost_micros or 0) / 1_000_000.0
            except Exception:
                # Fallback: use account.spend if the spend query fails
                total_spend = float(getattr(self.account, "spend", 0) or 0)

            # Available balance = total budget - spend since budget start
            balance = round(total_budget - total_spend, 2)
            return {
                "billing_type": "prepaid",
                "amount": balance,
                "status": "available",
                "total_budget": round(total_budget, 2),
                "spend_since_budget_start": round(total_spend, 2),
                "budget_start_date": spend_start,
            }
        except Exception as e:
            logger.warning(f"Google fetch billing failed for account {self.account.id}: {e}")
            return {"billing_type": "unknown", "amount": None, "status": "unavailable"}


class MetaAdsConnector(AdsConnector):
    def __init__(self, account: Account, start_date: Optional[str] = None, end_date: Optional[str] = None):
        super().__init__(account, start_date=start_date, end_date=end_date)
        self.api = None
        self.validate_credentials()

    def validate_credentials(self) -> bool:
        try:
            from facebook_business.api import FacebookAdsApi
            creds = self._parse_credentials()
            if not creds:
                return False
            FacebookAdsApi.init(access_token=creds["access_token"])
            self.api = FacebookAdsApi.get_default_api()
            self.is_valid = True
            return True
        except Exception as e:
            logger.error(f"Meta connector failed for account {self.account.id}: {e}")
            self.is_valid = False
            return False

    def _parse_credentials(self) -> Optional[Dict[str, Any]]:
        raw = self.account.meta_credentials or self.account.credentials
        if not raw:
            return None
        try:
            import json
            return json.loads(decrypt(raw))
        except Exception as e:
            logger.error(f"Failed to parse Meta credentials: {e}")
            return None

    def _date_params(self) -> Dict[str, Any]:
        if self.start_date and self.end_date:
            return {
                "time_range": {
                    "since": self.start_date,
                    "until": self.end_date,
                }
            }
        return {"date_preset": "last_30d"}

    def fetch_account_metrics(self) -> Dict[str, Any]:
        if not self.is_valid:
            return {"error": "Meta API not valid"}
        try:
            from facebook_business.adobjects.adaccount import AdAccount
            account_id = self.account.meta_external_id or self.account.external_id or ""
            if not account_id:
                return {"error": "No Meta ad account ID configured"}
            account = AdAccount(account_id)
            fields = ["spend", "clicks", "impressions", "conversions"]
            params = self._date_params()
            insights = account.get_insights(fields=fields, params=params)
            total_spend = 0.0
            total_clicks = 0
            total_impressions = 0
            total_conversions = 0
            for insight in insights:
                total_spend += float(insight.get("spend", 0))
                total_clicks += int(insight.get("clicks", 0) or 0)
                total_impressions += int(insight.get("impressions", 0) or 0)
                total_conversions += int(insight.get("conversions", 0) or 0)
            return {
                "spend": round(total_spend, 2),
                "clicks": total_clicks,
                "impressions": total_impressions,
                "conversions": total_conversions,
            }
        except Exception as e:
            logger.error(f"Meta fetch metrics failed: {e}")
            return {"error": str(e)}

    def fetch_campaigns(self) -> List[Dict[str, Any]]:
        if not self.is_valid:
            return []
        try:
            from facebook_business.adobjects.adaccount import AdAccount
            account_id = self.account.meta_external_id or self.account.external_id or ""
            if not account_id:
                return []
            account = AdAccount(account_id)
            fields = ["id", "name", "status", "daily_budget", "spend_cap"]
            campaigns = account.get_campaigns(fields=fields)
            return [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "status": c.get("status"),
                    "budget": (int(c.get("daily_budget", 0) or 0) / 100.0),
                    "spend": 0.0,
                    "clicks": 0,
                    "impressions": 0,
                    "conversions": 0,
                    "ctr": 0.0,
                    "cpa": 0.0,
                }
                for c in campaigns
            ]
        except Exception as e:
            logger.error(f"Meta fetch campaigns failed: {e}")
            return []

    def fetch_billing(self) -> Dict[str, Any]:
        """Fetch billing/balance data from Meta Marketing API.

        Meta doesn't expose a direct 'balance' field. We check:
        - spend_cap (daily/total spend cap) → postpaid with cap
        - spend (amount used today) → postpaid
        - No prepaid balance concept in standard Meta API

        Returns billing_type='postpaid' with spend amount if available.
        """
        if not self.is_valid:
            return {"billing_type": "unknown", "amount": None, "status": "unavailable"}
        try:
            from facebook_business.adobjects.adaccount import AdAccount
            account_id = self.account.meta_external_id or self.account.external_id or ""
            if not account_id:
                return {"billing_type": "unknown", "amount": None, "status": "unavailable"}
            account = AdAccount(account_id)
            # Fetch spend cap and current spend
            fields = ["spend_cap", "spend", "currency", "amount_spent"]
            try:
                account_data = account.api_get(fields=fields)
                spend_cap = float(account_data.get("spend_cap", 0) or 0)
                amount_spent = float(account_data.get("amount_spent", 0) or 0)
                if spend_cap > 0:
                    # Has a spend cap → postpaid with cap
                    return {"billing_type": "postpaid", "amount": amount_spent, "status": "available"}
                if amount_spent > 0:
                    return {"billing_type": "postpaid", "amount": amount_spent, "status": "available"}
            except Exception as e:
                logger.warning(f"Meta billing api_get failed for account {self.account.id}: {e}")
            return {"billing_type": "unknown", "amount": None, "status": "unavailable"}
        except Exception as e:
            logger.warning(f"Meta fetch billing failed for account {self.account.id}: {e}")
            return {"billing_type": "unknown", "amount": None, "status": "unavailable"}


def get_connector(account: Account, platform: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Optional[AdsConnector]:
    if platform == "google":
        return GoogleAdsConnector(account, start_date=start_date, end_date=end_date)
    if platform == "meta":
        return MetaAdsConnector(account, start_date=start_date, end_date=end_date)
    if account.account_type == AccountType.GOOGLE:
        return GoogleAdsConnector(account, start_date=start_date, end_date=end_date)
    if account.account_type == AccountType.META:
        return MetaAdsConnector(account, start_date=start_date, end_date=end_date)
    return None
