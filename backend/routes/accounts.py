"""
Account management and dashboard summary APIs.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.db.models import Account, AccountGroup, AccountType, AccountStatus
from backend.services.crypto import encrypt, decrypt
from backend.services.connectors import get_connector

router = APIRouter(prefix="/api", tags=["accounts"])


class AccountCreate(BaseModel):
    name: str
    group_id: Optional[int] = None
    currency: str = "INR"
    timezone: str = "Asia/Kolkata"
    refresh_interval_minutes: int = 60

    has_google: bool = True
    has_meta: bool = False

    google_external_id: Optional[str] = None
    meta_external_id: Optional[str] = None
    google_is_live: bool = False
    meta_is_live: bool = False


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    group_id: Optional[int] = None
    refresh_interval_minutes: Optional[int] = None
    audit_interval_minutes: Optional[int] = None
    is_active: Optional[bool] = None

    has_google: Optional[bool] = None
    has_meta: Optional[bool] = None

    google_external_id: Optional[str] = None
    meta_external_id: Optional[str] = None
    google_is_live: Optional[bool] = None
    meta_is_live: Optional[bool] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_developer_token: Optional[str] = None
    meta_app_id: Optional[str] = None
    meta_app_secret: Optional[str] = None
    redirect_base_url: Optional[str] = None


class GroupCreate(BaseModel):
    name: str


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db)):
    accounts = db.query(Account).all()
    return [a.to_dict() for a in accounts]


@router.get("/accounts/summary")
def dashboard_summary(start_date: Optional[str] = None, end_date: Optional[str] = None, db: Session = Depends(get_db)):
    """Grouped dashboard summary across all accounts. Optionally filtered by date range."""
    accounts = db.query(Account).filter(Account.is_active == True).all()
    groups = db.query(AccountGroup).all()

    # For now, account-level cached metrics are not date-filtered. Date range is passed through
    # for live connectors and audit context. A future reporting layer will store daily metrics.
    result = {
        "total_accounts": len(accounts),
        "total_spend": sum(a.spend for a in accounts),
        "total_conversions": sum(a.conversions for a in accounts),
        "total_clicks": sum(a.clicks for a in accounts),
        "total_impressions": sum(a.impressions for a in accounts),
        "start_date": start_date,
        "end_date": end_date,
        "groups": [],
        "ungrouped": [],
    }

    # Group accounts by client group and split into platform-specific items
    group_map = {g.id: g.name for g in groups}
    grouped = {}
    ungrouped = []
    for a in accounts:
        d = a.to_dict()
        for platform in ["google", "meta"]:
            if (platform == "google" and not a.has_google) or (platform == "meta" and not a.has_meta):
                continue
            tile = dict(d)
            tile["platform"] = platform
            tile["external_id"] = a.google_external_id if platform == "google" else a.meta_external_id or d.get("external_id")
            tile["is_live"] = a.google_is_live if platform == "google" else a.meta_is_live
            tile["credentials_masked"] = bool(a.google_credentials) if platform == "google" else bool(a.meta_credentials)
            if a.group_id:
                grouped.setdefault(a.group_id, {"group_id": a.group_id, "group_name": group_map.get(a.group_id, "Unknown"), "accounts": []})
                grouped[a.group_id]["accounts"].append(tile)
            else:
                ungrouped.append(tile)

    result["groups"] = list(grouped.values())
    result["ungrouped"] = ungrouped
    return result


@router.post("/accounts")
def create_account(req: AccountCreate, db: Session = Depends(get_db)):
    # Backward-compatible: at least one platform must be enabled; default type from first enabled platform
    if req.has_google and req.has_meta:
        account_type = AccountType.BOTH
        external_id = req.google_external_id or req.meta_external_id or ""
    elif req.has_google:
        account_type = AccountType.GOOGLE
        external_id = req.google_external_id or ""
    elif req.has_meta:
        account_type = AccountType.META
        external_id = req.meta_external_id or ""
    else:
        raise HTTPException(status_code=400, detail="At least one platform (Google or Meta) must be enabled")

    account = Account(
        name=req.name,
        account_type=account_type,
        external_id=external_id,
        group_id=req.group_id,
        has_google=req.has_google,
        has_meta=req.has_meta,
        google_external_id=req.google_external_id,
        meta_external_id=req.meta_external_id,
        google_credentials=None,
        meta_credentials=None,
        google_is_live=req.google_is_live,
        meta_is_live=req.meta_is_live,
        currency=req.currency,
        timezone=req.timezone,
        refresh_interval_minutes=req.refresh_interval_minutes,
        status=AccountStatus.DISCONNECTED,
        is_live=req.google_is_live or req.meta_is_live,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account.to_dict()


@router.put("/accounts/{account_id}")
def update_account(account_id: int, req: AccountUpdate, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if req.name is not None:
        account.name = req.name
    if req.group_id is not None:
        account.group_id = req.group_id
    if req.refresh_interval_minutes is not None:
        account.refresh_interval_minutes = req.refresh_interval_minutes
    if req.audit_interval_minutes is not None:
        account.audit_interval_minutes = req.audit_interval_minutes
    if req.is_active is not None:
        account.is_active = req.is_active

    if req.has_google is not None:
        account.has_google = req.has_google
    if req.has_meta is not None:
        account.has_meta = req.has_meta
    if req.google_external_id is not None:
        account.google_external_id = req.google_external_id
    if req.meta_external_id is not None:
        account.meta_external_id = req.meta_external_id
    if req.google_is_live is not None:
        account.google_is_live = req.google_is_live
    if req.meta_is_live is not None:
        account.meta_is_live = req.meta_is_live

    if req.google_client_id is not None:
        account.google_client_id = req.google_client_id or None
    if req.google_client_secret is not None:
        account.google_client_secret = req.google_client_secret or None
    if req.google_developer_token is not None:
        account.google_developer_token = req.google_developer_token or None
    if req.meta_app_id is not None:
        account.meta_app_id = req.meta_app_id or None
    if req.meta_app_secret is not None:
        account.meta_app_secret = req.meta_app_secret or None
    if req.redirect_base_url is not None:
        account.redirect_base_url = req.redirect_base_url or None

    # Keep legacy fields in sync
    if account.has_google and account.has_meta:
        account.account_type = AccountType.BOTH
    elif account.has_google:
        account.account_type = AccountType.GOOGLE
    elif account.has_meta:
        account.account_type = AccountType.META
    account.external_id = account.google_external_id or account.meta_external_id or ""
    account.is_live = account.google_is_live or account.meta_is_live

    db.commit()
    db.refresh(account)
    return account.to_dict()


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    db.delete(account)
    db.commit()
    return {"status": "success"}


@router.post("/accounts/{account_id}/refresh")
def refresh_account(account_id: int, start_date: Optional[str] = None, end_date: Optional[str] = None, platform: Optional[str] = None, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    target_platform = platform
    if not target_platform:
        if account.account_type == AccountType.GOOGLE:
            target_platform = "google"
        elif account.account_type == AccountType.META:
            target_platform = "meta"
        elif account.has_google:
            target_platform = "google"
        elif account.has_meta:
            target_platform = "meta"
        else:
            raise HTTPException(status_code=400, detail="No platform enabled for this account")

    platform_creds = account.google_credentials if target_platform == "google" else account.meta_credentials
    platform_live = account.google_is_live if target_platform == "google" else account.meta_is_live
    use_live = platform_live and bool(platform_creds)

    if use_live:
        connector = get_connector(account, platform=target_platform, start_date=start_date, end_date=end_date)
        if connector and connector.is_valid:
            metrics = connector.fetch_account_metrics()
            if "error" not in metrics:
                # Aggregate into account-level metrics: if only one platform enabled, overwrite; otherwise add
                if not (account.has_google and account.has_meta):
                    account.spend = metrics.get("spend", 0.0)
                    account.clicks = metrics.get("clicks", 0)
                    account.impressions = metrics.get("impressions", 0)
                    account.conversions = metrics.get("conversions", 0)
                else:
                    account.spend = (account.spend or 0.0) + metrics.get("spend", 0.0)
                    account.clicks = (account.clicks or 0) + metrics.get("clicks", 0)
                    account.impressions = (account.impressions or 0) + metrics.get("impressions", 0)
                    account.conversions = (account.conversions or 0) + metrics.get("conversions", 0)
                account.ctr = round((account.clicks / account.impressions) * 100, 2) if account.impressions else 0.0
                account.cpa = round(account.spend / account.conversions, 2) if account.conversions else 0.0
                account.status = AccountStatus.HEALTHY
                account.last_sync_at = __import__('datetime').datetime.utcnow()
                account.last_sync_error = None
                db.commit()
                db.refresh(account)
                data = account.to_dict()
                data["platform"] = target_platform
                return data
            else:
                account.last_sync_error = metrics.get("error")
                account.status = AccountStatus.DISCONNECTED
        else:
            account.last_sync_error = "Invalid credentials or connector not configured"
            account.status = AccountStatus.DISCONNECTED

    # Fallback to mock data
    refresh_account_internal(account)
    db.commit()
    db.refresh(account)
    data = account.to_dict()
    data["platform"] = target_platform
    return data


@router.get("/accounts/{account_id}")
def get_account(account_id: int, start_date: Optional[str] = None, end_date: Optional[str] = None, platform: Optional[str] = None, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    data = account.to_dict()
    data["start_date"] = start_date
    data["end_date"] = end_date
    data["platform"] = platform
    return data


@router.get("/account-groups")
def list_groups(db: Session = Depends(get_db)):
    groups = db.query(AccountGroup).all()
    return [{"id": g.id, "name": g.name} for g in groups]


@router.post("/account-groups")
def create_group(req: GroupCreate, db: Session = Depends(get_db)):
    group = AccountGroup(name=req.name)
    db.add(group)
    db.commit()
    db.refresh(group)
    return {"id": group.id, "name": group.name}


@router.post("/seed-demo-accounts")
def seed_demo_accounts(db: Session = Depends(get_db)):
    """Seed demo accounts if none exist."""
    if db.query(Account).first():
        return {"status": "skipped", "message": "Accounts already exist"}

    groups = ["Education", "E-Commerce", "SaaS", "Real Estate"]
    group_objs = {}
    for g in groups:
        grp = AccountGroup(name=g)
        db.add(grp)
        db.flush()
        group_objs[g] = grp.id

    demo_accounts = [
        {"name": "BBA Brand - Google", "type": "google", "external_id": "123-456-7890", "group": "Education"},
        {"name": "BBA Brand - Meta", "type": "meta", "external_id": "act_123456789", "group": "Education"},
        {"name": "MBA Lead Gen - Google", "type": "google", "external_id": "123-456-7891", "group": "Education"},
        {"name": "Shoes Store - Meta", "type": "meta", "external_id": "act_987654321", "group": "E-Commerce"},
        {"name": "SaaS Platform - Google", "type": "google", "external_id": "456-789-0123", "group": "SaaS"},
        {"name": "CRM Campaign - Meta", "type": "meta", "external_id": "act_555666777", "group": "SaaS"},
    ]

    for da in demo_accounts:
        acc = Account(
            name=da["name"],
            account_type=AccountType(da["type"]),
            external_id=da["external_id"],
            group_id=group_objs.get(da["group"]),
            currency="INR",
            status=AccountStatus.DISCONNECTED,
        )
        db.add(acc)
    db.commit()

    # Refresh all to generate initial mock metrics
    for acc in db.query(Account).all():
        refresh_account_internal(acc)
    db.commit()

    return {"status": "success", "accounts_added": len(demo_accounts)}


def refresh_account_internal(account: Account):
    import random, datetime
    spend = random.randint(5000, 150000)
    conversions = random.randint(5, 300)
    clicks = random.randint(200, 5000)
    impressions = clicks * random.randint(20, 80)
    budget = spend * random.uniform(1.1, 1.5)
    ctr = (clicks / impressions) * 100 if impressions else 0.0
    cpa = spend / conversions if conversions else 0.0

    account.spend = round(spend, 2)
    account.conversions = conversions
    account.clicks = clicks
    account.impressions = impressions
    account.ctr = round(ctr, 2)
    account.cpa = round(cpa, 2)
    account.budget = round(budget, 2)
    account.budget_used_pct = round((spend / budget) * 100, 2) if budget else 0.0
    account.last_sync_at = datetime.datetime.utcnow()

    if account.budget_used_pct > 90:
        account.status = AccountStatus.CRITICAL
    elif account.budget_used_pct > 70:
        account.status = AccountStatus.WARNING
    else:
        account.status = AccountStatus.HEALTHY
