"""
CRM connector services for Salesforce and LeadSquared.
Live API calls only.
"""
import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from backend.services.config import load_config
from backend.db.models import Account

logger = logging.getLogger("AdOptima")


class CRMConnector:
    """Base for CRM connectors."""
    def __init__(self, account: Account, start_date: Optional[str] = None, end_date: Optional[str] = None):
        self.account = account
        self.start_date = start_date or "2025-11-28"
        self.end_date = end_date or datetime.utcnow().strftime("%Y-%m-%d")
        self.is_valid = False

    def validate_credentials(self) -> bool:
        return False

    def fetch_leads(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def fetch_opportunities(self) -> List[Dict[str, Any]]:
        raise NotImplementedError


class SalesforceConnector(CRMConnector):
    def __init__(self, account: Account, start_date: Optional[str] = None, end_date: Optional[str] = None):
        super().__init__(account, start_date=start_date, end_date=end_date)
        self.cfg = self._load_cfg()
        self.validate_credentials()

    def _load_cfg(self) -> Dict[str, Any]:
        cfg = load_config()
        return {
            "instance_url": cfg.get("salesforce_url", ""),
            "client_id": cfg.get("salesforce_client_id", ""),
            "client_secret": cfg.get("salesforce_client_secret", ""),
            "refresh_token": cfg.get("salesforce_refresh_token", ""),
        }

    def validate_credentials(self) -> bool:
        required = [self.cfg["client_id"], self.cfg["client_secret"], self.cfg["refresh_token"], self.cfg["instance_url"]]
        self.is_valid = all(required)
        if not self.is_valid:
            logger.info(f"Salesforce not configured for account {self.account.id}; returning empty data.")
        return self.is_valid

    def _access_token(self) -> Optional[str]:
        if not self.is_valid:
            return None
        try:
            import requests
            url = f"{self.cfg['instance_url'].rstrip('/')}/services/oauth2/token"
            data = {
                "grant_type": "refresh_token",
                "client_id": self.cfg["client_id"],
                "client_secret": self.cfg["client_secret"],
                "refresh_token": self.cfg["refresh_token"],
            }
            r = requests.post(url, data=data, timeout=30)
            r.raise_for_status()
            return r.json().get("access_token")
        except Exception as e:
            logger.error(f"Salesforce token refresh failed: {e}")
            return None

    def fetch_leads(self) -> List[Dict[str, Any]]:
        token = self._access_token()
        if token:
            return self._fetch_live_leads(token)
        return []

    def fetch_opportunities(self) -> List[Dict[str, Any]]:
        token = self._access_token()
        if token:
            return self._fetch_live_opportunities(token)
        return []

    def _fetch_live_leads(self, token: str) -> List[Dict[str, Any]]:
        try:
            import requests
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            soql = (
                "SELECT Id, FirstName, LastName, Email, Phone, Company, Status, LeadSource, CreatedDate, "
                f"Owner.Name FROM Lead WHERE CreatedDate >= {self.start_date}T00:00:00Z AND CreatedDate <= {self.end_date}T23:59:59Z"
            )
            if self.account.name:
                escaped = self.account.name.replace("'", "\\'")
                soql += f" AND Company LIKE '%{escaped}%'"
            url = f"{self.cfg['instance_url'].rstrip('/')}/services/data/v59.0/query/?q={requests.utils.quote(soql)}"
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            records = r.json().get("records", [])
            return [self._normalize_lead(rec) for rec in records]
        except Exception as e:
            logger.error(f"Salesforce live leads failed: {e}")
            return []

    def _fetch_live_opportunities(self, token: str) -> List[Dict[str, Any]]:
        try:
            import requests
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            soql = (
                "SELECT Id, Name, Amount, StageName, Probability, CloseDate, LeadSource, CreatedDate, "
                f"Account.Name FROM Opportunity WHERE CreatedDate >= {self.start_date}T00:00:00Z AND CreatedDate <= {self.end_date}T23:59:59Z"
            )
            if self.account.name:
                escaped = self.account.name.replace("'", "\\'")
                soql += f" AND Account.Name LIKE '%{escaped}%'"
            url = f"{self.cfg['instance_url'].rstrip('/')}/services/data/v59.0/query/?q={requests.utils.quote(soql)}"
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            records = r.json().get("records", [])
            return [self._normalize_opportunity(rec) for rec in records]
        except Exception as e:
            logger.error(f"Salesforce live opportunities failed: {e}")
            return []

    def _normalize_lead(self, rec: Dict[str, Any]) -> Dict[str, Any]:
        owner = rec.get("Owner") or {}
        return {
            "id": rec.get("Id"),
            "first_name": rec.get("FirstName"),
            "last_name": rec.get("LastName"),
            "email": rec.get("Email"),
            "phone": rec.get("Phone"),
            "company": rec.get("Company"),
            "status": rec.get("Status"),
            "source": rec.get("LeadSource"),
            "created_at": rec.get("CreatedDate"),
            "owner": owner.get("Name"),
            "platform": "salesforce",
        }

    def _normalize_opportunity(self, rec: Dict[str, Any]) -> Dict[str, Any]:
        account = rec.get("Account") or {}
        return {
            "id": rec.get("Id"),
            "name": rec.get("Name"),
            "amount": rec.get("Amount") or 0.0,
            "stage": rec.get("StageName"),
            "probability": rec.get("Probability") or 0,
            "close_date": rec.get("CloseDate"),
            "source": rec.get("LeadSource"),
            "created_at": rec.get("CreatedDate"),
            "account_name": account.get("Name"),
            "platform": "salesforce",
        }


class LeadSquaredConnector(CRMConnector):
    def __init__(self, account: Account, start_date: Optional[str] = None, end_date: Optional[str] = None):
        super().__init__(account, start_date=start_date, end_date=end_date)
        self.cfg = self._load_cfg()
        self.validate_credentials()

    def _load_cfg(self) -> Dict[str, Any]:
        cfg = load_config()
        return {
            "base_url": cfg.get("leadsquared_base_url", "https://api.leadsquared.com"),
            "access_key": cfg.get("leadsquared_access_key", ""),
            "secret_key": cfg.get("leadsquared_secret_key", ""),
        }

    def validate_credentials(self) -> bool:
        required = [self.cfg["access_key"], self.cfg["secret_key"], self.cfg["base_url"]]
        self.is_valid = all(required)
        if not self.is_valid:
            logger.info(f"LeadSquared not configured for account {self.account.id}; returning empty data.")
        return self.is_valid

    def _auth_params(self) -> str:
        import urllib.parse
        return urllib.parse.urlencode({
            "accessKey": self.cfg["access_key"],
            "secretKey": self.cfg["secret_key"],
        })

    def fetch_leads(self) -> List[Dict[str, Any]]:
        if self.is_valid:
            return self._fetch_live_leads()
        return []

    def fetch_opportunities(self) -> List[Dict[str, Any]]:
        # LeadSquared does not have native Opportunities; return empty.
        return []

    def _fetch_live_leads(self) -> List[Dict[str, Any]]:
        try:
            import requests
            base = self.cfg["base_url"].rstrip("/")
            if not base.endswith("/v2"):
                base = base.rstrip("/") + "/v2"
            url = f"{base}/LeadManagement.svc/Leads.RecentlyModified"
            payload = {
                "Parameter": {
                    "FromDate": f"{self.start_date} 00:00:00",
                    "ToDate": f"{self.end_date} 23:59:59",
                },
                "Columns": {
                    "Include_CSV": "ProspectID,FirstName,LastName,EmailAddress,Phone,Source,CreatedOn,OwnerId,ProspectStage,mx_Student_Source,SourceCampaign"
                },
                "Paging": {"PageIndex": 1, "PageSize": 5000},
                "Sorting": {"ColumnName": "ProspectAutoId", "Direction": "1"},
            }
            logger.info(f"LeadSquared request: {url} payload={payload}")
            r = requests.post(url, params={"accessKey": self.cfg["access_key"], "secretKey": self.cfg["secret_key"]}, json=payload, timeout=60)
            logger.info(f"LeadSquared response status: {r.status_code}")
            r.raise_for_status()
            response = r.json()
            records = response.get("Leads", [])
            logger.info(f"LeadSquared returned {len(records)} records (total={response.get('RecordCount')})")
            if not records:
                logger.info(f"LeadSquared empty response: {response}")
            return [self._normalize_lead(rec) for rec in records]
        except Exception as e:
            logger.error(f"LeadSquared live leads failed: {e}")
            return []

    def _normalize_lead(self, rec: Dict[str, Any]) -> Dict[str, Any]:
        props = {}
        for item in rec.get("LeadPropertyList", []):
            attr = item.get("Attribute")
            val = item.get("Value")
            if attr:
                props[attr] = val
        return {
            "id": props.get("ProspectID"),
            "first_name": props.get("FirstName"),
            "last_name": props.get("LastName"),
            "email": props.get("EmailAddress"),
            "phone": props.get("Phone"),
            "company": props.get("Company"),
            "status": props.get("ProspectStage"),
            "source": props.get("mx_Student_Source") or props.get("Source"),
            "source_campaign": props.get("SourceCampaign"),
            "created_at": props.get("CreatedOn"),
            "owner": props.get("OwnerId"),
            "platform": "leadsquared",
        }


def get_crm_connector(platform: str, account: Account, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Optional[CRMConnector]:
    if platform == "salesforce":
        return SalesforceConnector(account, start_date=start_date, end_date=end_date)
    if platform == "leadsquared":
        return LeadSquaredConnector(account, start_date=start_date, end_date=end_date)
    return None


def fetch_all_crm_data(account: Account, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    salesforce = get_crm_connector("salesforce", account, start_date, end_date)
    leadsquared = get_crm_connector("leadsquared", account, start_date, end_date)
    sf_leads = salesforce.fetch_leads() if salesforce else []
    sf_opps = salesforce.fetch_opportunities() if salesforce else []
    ls_leads = leadsquared.fetch_leads() if leadsquared else []
    ls_opps = leadsquared.fetch_opportunities() if leadsquared else []
    return {
        "salesforce": {"leads": sf_leads, "opportunities": sf_opps, "connected": bool(salesforce and salesforce.is_valid)},
        "leadsquared": {"leads": ls_leads, "opportunities": ls_opps, "connected": bool(leadsquared and leadsquared.is_valid)},
    }


if __name__ == "__main__":
    from backend.db.models import AccountType
    a = Account(id=1, name="DSU", account_type=AccountType.BOTH)
    data = fetch_all_crm_data(a)
    print(json.dumps(data, indent=2, default=str))