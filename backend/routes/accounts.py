"""
Account management and dashboard summary APIs.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.db.models import Account, AccountGroup, AccountType, AccountStatus, User, UserAccountAssignment
from backend.db.revenueops_models import RevClient, RevClientStatus
from backend.services.crypto import encrypt, decrypt
from backend.services.connectors import get_connector
from backend.routes.auth import get_current_user_required

router = APIRouter(prefix="/api", tags=["accounts"])


def _filter_accounts_for_user(query, user: User):
    """BM (role=user) sees only assigned accounts. Admin/superadmin see all."""
    if user.role in ("admin", "superadmin"):
        return query
    return query.join(UserAccountAssignment, UserAccountAssignment.account_id == Account.id).filter(
        UserAccountAssignment.user_id == user.id
    )


def _badges_for_tile(account, platform: str, db: Session) -> dict:
    """Compute API + Performance health badges for a dashboard tile.

    Uses cached metrics + LSQ mirror leads for today. Falls back gracefully
    if leads cannot be fetched.
    """
    from backend.services.health import compute_health_badges
    from datetime import datetime, timedelta

    today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    leads_today = 0
    try:
        from backend.services.lsq_mirror import count_leads_by_course
        counts = count_leads_by_course(db, account.id, today, today)
        leads_today = sum(counts.values())
    except Exception:
        pass

    # API success is inferred from whether the account has a live platform with
    # valid credentials and no last_sync_error.
    platform_live = account.google_is_live if platform == "google" else account.meta_is_live
    platform_creds = account.google_credentials if platform == "google" else account.meta_credentials
    api_success = bool(platform_live and platform_creds and not account.last_sync_error)

    return compute_health_badges(
        account, api_success=api_success, platform=platform, leads=leads_today,
        active_start=0, active_end=23,
    )


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

    crm_type: str = "none"
    crm_credentials: Optional[str] = None
    target_cpa: Optional[float] = None

    brand_name: Optional[str] = None
    contact_person: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    business_manager_id: Optional[int] = None


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
    lsq_access_key: Optional[str] = None
    lsq_secret_key: Optional[str] = None
    lsq_base_url: Optional[str] = None

    crm_type: Optional[str] = None
    crm_credentials: Optional[str] = None
    target_cpa: Optional[float] = None

    brand_name: Optional[str] = None
    contact_person: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    business_manager_id: Optional[int] = None


class GroupCreate(BaseModel):
    name: str


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    q = db.query(Account)
    q = _filter_accounts_for_user(q, user)
    accounts = q.all()
    return [a.to_dict() for a in accounts]


@router.get("/accounts/summary")
def dashboard_summary(start_date: Optional[str] = None, end_date: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """Grouped dashboard summary across all accounts. Optionally filtered by date range.
    Only live accounts (DSU, DSI) contribute to totals and tile metrics; non-live accounts show zeros.
    BM users only see their assigned accounts."""
    q = db.query(Account).filter(Account.is_active == True)
    q = _filter_accounts_for_user(q, user)
    accounts = q.all()
    groups = db.query(AccountGroup).all()

    live_accounts = [a for a in accounts if a.is_live]
    result = {
        "total_accounts": len(accounts),
        "total_spend": sum(a.spend for a in live_accounts),
        "total_conversions": sum(a.conversions for a in live_accounts),
        "total_clicks": sum(a.clicks for a in live_accounts),
        "total_impressions": sum(a.impressions for a in live_accounts),
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
        # Zero out metrics for non-live accounts so dashboard only shows real data
        if not a.is_live:
            d["spend"] = 0.0
            d["conversions"] = 0.0
            d["clicks"] = 0.0
            d["impressions"] = 0.0
            d["ctr"] = 0.0
            d["cpa"] = 0.0
            d["budget"] = 0.0
            d["budget_used_pct"] = 0.0
        for platform in ["google", "meta"]:
            if (platform == "google" and not a.has_google) or (platform == "meta" and not a.has_meta):
                continue
            tile = dict(d)
            tile["platform"] = platform
            tile["external_id"] = a.google_external_id if platform == "google" else a.meta_external_id or d.get("external_id")
            tile["is_live"] = a.google_is_live if platform == "google" else a.meta_is_live
            tile["credentials_masked"] = bool(a.google_credentials) if platform == "google" else bool(a.meta_credentials)
            # Health badges
            _hb = _badges_for_tile(a, platform, db)
            tile["api_health"] = _hb["api_health"]
            tile["perf_health"] = _hb["perf_health"]
            # Billing chip
            from backend.services.billing import get_billing_for_account
            tile["billing"] = get_billing_for_account(a)
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
        crm_type=req.crm_type or "none",
        crm_credentials=req.crm_credentials,
        target_cpa=req.target_cpa,
        brand_name=req.brand_name,
        contact_person=req.contact_person,
        contact_email=req.contact_email,
        contact_phone=req.contact_phone,
        business_manager_id=req.business_manager_id,
    )
    db.add(account)
    db.flush()

    # Auto-create or link a RevenueOps client
    existing_client = db.query(RevClient).filter(RevClient.client_name == req.name).first()
    if existing_client:
        account.rev_client_id = existing_client.id
    else:
        rev_client = RevClient(
            client_name=req.name,
            brand_name=req.brand_name,
            contact_person=req.contact_person,
            contact_email=req.contact_email,
            contact_phone=req.contact_phone,
            business_manager_id=req.business_manager_id,
            client_status=RevClientStatus.ACTIVE.value,
        )
        db.add(rev_client)
        db.flush()
        account.rev_client_id = rev_client.id

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

    if req.lsq_access_key is not None:
        account.lsq_access_key = req.lsq_access_key or None
    if req.lsq_secret_key is not None:
        account.lsq_secret_key = req.lsq_secret_key or None
    if req.lsq_base_url is not None:
        account.lsq_base_url = req.lsq_base_url or None

    if req.crm_type is not None:
        account.crm_type = req.crm_type or "none"
    if req.crm_credentials is not None:
        account.crm_credentials = req.crm_credentials or None
    if req.target_cpa is not None:
        account.target_cpa = req.target_cpa or None

    if req.brand_name is not None:
        account.brand_name = req.brand_name or None
    if req.contact_person is not None:
        account.contact_person = req.contact_person or None
    if req.contact_email is not None:
        account.contact_email = req.contact_email or None
    if req.contact_phone is not None:
        account.contact_phone = req.contact_phone or None
    if req.business_manager_id is not None:
        account.business_manager_id = req.business_manager_id or None

    # Keep legacy fields in sync
    if account.has_google and account.has_meta:
        account.account_type = AccountType.BOTH
    elif account.has_google:
        account.account_type = AccountType.GOOGLE
    elif account.has_meta:
        account.account_type = AccountType.META
    account.external_id = account.google_external_id or account.meta_external_id or ""
    account.is_live = account.google_is_live or account.meta_is_live

    # Sync contact fields to linked RevenueOps client
    if account.rev_client_id:
        rev_client = db.query(RevClient).filter(RevClient.id == account.rev_client_id).first()
        if rev_client:
            if req.name is not None:
                rev_client.client_name = req.name
            if req.brand_name is not None:
                rev_client.brand_name = req.brand_name or None
            if req.contact_person is not None:
                rev_client.contact_person = req.contact_person or None
            if req.contact_email is not None:
                rev_client.contact_email = req.contact_email or None
            if req.contact_phone is not None:
                rev_client.contact_phone = req.contact_phone or None
            if req.business_manager_id is not None:
                rev_client.business_manager_id = req.business_manager_id or None

    db.commit()
    db.refresh(account)
    return account.to_dict()


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, delete_revops: bool = False, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    rev_client_id = account.rev_client_id
    db.delete(account)
    if delete_revops and rev_client_id:
        rev_client = db.query(RevClient).filter(RevClient.id == rev_client_id).first()
        if rev_client:
            db.delete(rev_client)
    db.commit()
    return {"status": "success", "rev_client_deleted": delete_revops and bool(rev_client_id)}


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
                # Health badges: compute API + Performance health
                from backend.services.health import compute_health_badges
                from datetime import datetime as _dt, timedelta as _td
                _today = (_dt.utcnow() + _td(hours=5, minutes=30)).strftime("%Y-%m-%d")
                _leads_today = 0
                try:
                    from backend.services.lsq_mirror import count_leads_by_course as _clbc
                    _counts = _clbc(db, account.id, _today, _today)
                    _leads_today = sum(_counts.values())
                except Exception:
                    pass
                _badges = compute_health_badges(account, api_success=True, platform=target_platform, leads=_leads_today, active_start=0, active_end=23)
                _api_status = _badges["api_health"]["status"]
                _perf_status = _badges["perf_health"]["status"]
                if _api_status == "DISCONNECTED":
                    account.status = AccountStatus.DISCONNECTED
                elif _perf_status == "CRITICAL":
                    account.status = AccountStatus.CRITICAL
                elif _perf_status in ("WARNING", "UNKNOWN"):
                    account.status = AccountStatus.WARNING
                else:
                    account.status = AccountStatus.HEALTHY
                account.last_sync_at = __import__('datetime').datetime.utcnow()
                account.last_sync_error = None
                # Fetch and cache billing data (best-effort)
                try:
                    _billing = connector.fetch_billing()
                    if _billing:
                        import json as _json
                        account.billing_cache = _json.dumps(_billing)
                except Exception:
                    pass
                db.commit()
                db.refresh(account)
                data = account.to_dict()
                data["platform"] = target_platform
                data["api_health"] = _badges["api_health"]
                data["perf_health"] = _badges["perf_health"]
                from backend.services.billing import get_billing_for_account
                data["billing"] = get_billing_for_account(account)
                return data
            else:
                account.last_sync_error = metrics.get("error")
                account.status = AccountStatus.DISCONNECTED
        else:
            account.last_sync_error = "Invalid credentials or connector not configured"
            account.status = AccountStatus.DISCONNECTED

    db.commit()
    db.refresh(account)
    data = account.to_dict()
    data["platform"] = target_platform
    # Compute badges even on failure so frontend can show DISCONNECTED / UNKNOWN
    from backend.services.health import compute_health_badges
    _badges = compute_health_badges(account, api_success=False, platform=target_platform, active_start=0, active_end=23)
    data["api_health"] = _badges["api_health"]
    data["perf_health"] = _badges["perf_health"]
    from backend.services.billing import get_billing_for_account
    data["billing"] = get_billing_for_account(account)
    return data


@router.get("/accounts/{account_id}")
def get_account(account_id: int, start_date: Optional[str] = None, end_date: Optional[str] = None, platform: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if user.role == "user" and account_id not in user.assigned_account_ids():
        raise HTTPException(status_code=403, detail="Access denied to this account")
    data = account.to_dict()
    # Zero out metrics for non-live accounts
    if not account.is_live:
        data["spend"] = 0.0
        data["conversions"] = 0.0
        data["clicks"] = 0.0
        data["impressions"] = 0.0
        data["ctr"] = 0.0
        data["cpa"] = 0.0
        data["budget"] = 0.0
        data["budget_used_pct"] = 0.0
    data["start_date"] = start_date
    data["end_date"] = end_date
    data["platform"] = platform
    return data


@router.get("/account-groups")
def list_groups(db: Session = Depends(get_db)):
    groups = db.query(AccountGroup).all()
    return [{"id": g.id, "name": g.name} for g in groups]


@router.get("/accounts/{account_id}/leads")
def get_account_leads(account_id: int, start_date: Optional[str] = None, end_date: Optional[str] = None, db: Session = Depends(get_db)):
    """Fetch lead count from LeadSquared for a live account (DSU/DSI). Returns 0 for non-live accounts."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if not account.is_live:
        return {"account_id": account_id, "leads": 0, "source": "leadsquared"}

    from datetime import datetime, timedelta
    if not end_date:
        end_date = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    if not start_date:
        start_date = end_date

    try:
        from backend.services.dsu_data import _fetch_lsq_leads
        course_leads = _fetch_lsq_leads(start_date, end_date, account_id=account_id)
        total = sum(course_leads.values())
        return {"account_id": account_id, "leads": total, "source": "leadsquared", "by_course": course_leads}
    except Exception as e:
        return {"account_id": account_id, "leads": 0, "source": "leadsquared", "error": str(e)}


@router.post("/account-groups")
def create_group(req: GroupCreate, db: Session = Depends(get_db)):
    group = AccountGroup(name=req.name)
    db.add(group)
    db.commit()
    db.refresh(group)
    return {"id": group.id, "name": group.name}


@router.post("/seed-demo-accounts")
def seed_demo_accounts(db: Session = Depends(get_db)):
    """Seed demo accounts if none exist. Deprecated — disabled."""
    return {"status": "skipped", "message": "Demo account seeding is disabled. Create accounts manually."}
