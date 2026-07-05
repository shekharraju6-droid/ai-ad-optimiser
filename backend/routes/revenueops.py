"""
RevenueOps API routes: clients, billing models, invoices, payments,
documents, reminders, followup notes, audit logs, dashboard, reports, settings, RBAC.
"""
import json
import os
from datetime import datetime, date, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from backend.db.database import get_db
from sqlalchemy import false
from backend.db.models import User, Account, UserAccountAssignment
from backend.db.revenueops_models import (
    RevClient, RevClientStatus, ClientBillingModel, BillingModelType, BillingFrequency,
    RevInvoice, InvoiceStatus, PaymentStatus, PaymentMode,
    RevPayment, RevDocument, DocType,
    RevReminder, ReminderType, ReminderPriority, ReminderStatus,
    FollowupNote, AuditLog, RevSetting, RevRole,
)
from backend.services.activity_log import log_activity
from backend.routes.auth import get_current_user_required
from backend.routes.accounts import _filter_accounts_for_user as _filter_accounts_for_user_helper

router = APIRouter(prefix="/api/revenueops", tags=["revenueops"])


def _audit(db: Session, user_id: int, action: str, entity_type: str, entity_id: int = None, old_val: str = None, new_val: str = None):
    log = AuditLog(user_id=user_id, action=action, entity_type=entity_type, entity_id=entity_id, old_value=old_val, new_value=new_val)
    db.add(log)
    db.commit()


def _client_name_for_log(db: Session, client_id: int) -> tuple:
    """Return (client_name, account_id, account_name) for a RevClient."""
    c = db.query(RevClient).filter(RevClient.id == client_id).first()
    if not c:
        return None, None, None
    account = db.query(Account).filter(
        or_(Account.rev_client_id == c.id, Account.id == c.account_id)
    ).first()
    return c.client_name, account.id if account else None, account.name if account else c.client_name


def _check_rev_role(user: User, allowed_roles: list):
    if user.role in ("admin", "superadmin"):
        return True
    if user.rev_role in allowed_roles:
        return True
    raise HTTPException(status_code=403, detail=f"Access denied. Required role: {allowed_roles}")


def _bm_client_filter(query, user: User):
    """Filter RevClient visibility by role using central Account linkage.

    - superadmin/admin: see all clients.
    - business_manager: see only clients where business_manager_id == user.id.
    - regular user (role=user or newuser) without rev_role: see clients whose linked central
      account is in the user's assigned_account_ids. Empty assignment list = no clients.
    """
    if user.role in ("admin", "superadmin"):
        return query
    if user.rev_role == "business_manager":
        return query.filter(RevClient.business_manager_id == user.id)
    # Regular user/BM/User: restrict to assigned accounts.
    if user.role in ("user", "newuser"):
        assigned_ids = user.assigned_account_ids()
        if not assigned_ids:
            return query.filter(false())
        return query.join(
            Account,
            or_(
                Account.rev_client_id == RevClient.id,
                RevClient.account_id == Account.id,
            ),
            isouter=False,
        ).filter(Account.id.in_(assigned_ids))
    return query


def _client_view_query(db: Session, user: User):
    """Return a query that joins RevClient with central Account so RevenueOps lists
    show the single client master fields while keeping RevClient.id as the client_id
    anchor for invoices/payments.
    """
    q = db.query(RevClient, Account).join(
        Account,
        or_(
            Account.rev_client_id == RevClient.id,
            RevClient.account_id == Account.id,
        ),
        isouter=True,
    )
    q = _bm_client_filter(q.with_entities(RevClient, Account), user)
    # _bm_client_filter operates on a RevClient query; restoring projection
    q = db.query(RevClient, Account).select_from(q.subquery())
    return q


def _client_view_dict(rev_client: RevClient, account: Account = None):
    """Build a unified client dict preferring central Account fields but keeping
    RevClient.id as the canonical client_id.
    """
    bm = rev_client.business_manager
    bm_name = bm.full_name or bm.email if bm else None
    if account:
        # Prefer central account fields, fallback to RevClient fields
        return {
            "id": rev_client.id,
            "account_id": account.id,
            "client_name": account.name or rev_client.client_name,
            "brand_name": account.brand_name or rev_client.brand_name,
            "company_name": rev_client.company_name,
            "contact_person": account.contact_person or rev_client.contact_person,
            "contact_email": account.contact_email or rev_client.contact_email,
            "contact_phone": account.contact_phone or rev_client.contact_phone,
            "business_manager_id": account.business_manager_id or rev_client.business_manager_id,
            "business_manager_name": bm_name,
            "client_status": (account.client_status or "Active").lower().replace(" ", "_"),
            "invoice_day": account.invoice_day if account.invoice_day is not None else rev_client.invoice_day,
            "default_due_days": account.payment_due_days if account.payment_due_days is not None else rev_client.default_due_days,
            "billing_amount": account.billing_amount,
            "gst_number": account.gst_number,
            "address": account.address,
            "state": account.state,
            "state_code": account.state_code,
            "remarks": rev_client.remarks,
            "created_at": rev_client.created_at.isoformat() if rev_client.created_at else None,
            "updated_at": rev_client.updated_at.isoformat() if rev_client.updated_at else None,
        }
    return rev_client.to_dict()


def _dashboard_client_filter_for_user(query, user: User):
    """Return a subquery / filter of RevClient IDs the current user may see.

    Same rules as _bm_client_filter but returns a query object of RevClient.id.
    """
    q = db.query(RevClient.id)  # placeholder; caller rebuilds
    if user.role in ("admin", "superadmin"):
        return None  # no restriction
    if user.rev_role == "business_manager":
        return db.query(RevClient.id).filter(RevClient.business_manager_id == user.id)
    assigned_ids = user.assigned_account_ids()
    if not assigned_ids:
        return db.query(RevClient.id).filter(false())
    return db.query(RevClient.id).join(
        Account,
        or_(
            Account.rev_client_id == RevClient.id,
            RevClient.account_id == Account.id,
        ),
        isouter=False,
    ).filter(Account.id.in_(assigned_ids))


def _bm_filter(query, user: User, bm_col):
    if user.role in ("admin", "superadmin"):
        return query
    if user.rev_role == "business_manager":
        return query.filter(bm_col == user.id)
    return query


def _generate_invoice_reminders(inv: RevInvoice, db: Session):
    """Auto-create due-date reminders for an invoice."""
    if not inv.due_date or inv.invoice_status in (InvoiceStatus.CANCELLED.value, InvoiceStatus.PAID.value):
        return
    try:
        due = datetime.strptime(inv.due_date, "%Y-%m-%d").date()
    except Exception:
        return
    today = date.today()
    # Remove existing auto-generated reminders for this invoice
    db.query(RevReminder).filter(
        RevReminder.invoice_id == inv.id,
        RevReminder.auto_generated == True,
        RevReminder.reminder_status != ReminderStatus.DONE.value,
    ).delete()
    due_amount = inv.outstanding_amount or inv.invoice_amount or 0
    reminders_to_create = []
    for days_before, rtype in [(3, ReminderType.DUE_IN_3_DAYS.value), (2, ReminderType.DUE_IN_2_DAYS.value), (1, ReminderType.DUE_IN_1_DAY.value)]:
        reminder_date = (due - __import__("datetime").timedelta(days=days_before)).isoformat()
        if reminder_date >= today.isoformat():
            reminders_to_create.append({
                "client_id": inv.client_id,
                "invoice_id": inv.id,
                "business_manager_id": inv.business_manager_id,
                "reminder_type": rtype,
                "priority": ReminderPriority.MEDIUM.value,
                "reminder_status": ReminderStatus.OPEN.value,
                "due_amount": due_amount,
                "due_date": inv.due_date,
                "next_followup_date": reminder_date,
                "auto_generated": True,
                "notes": f"Auto-generated: {rtype.replace('_', ' ')}",
            })
    # Due today reminder
    if due >= today:
        reminders_to_create.append({
            "client_id": inv.client_id,
            "invoice_id": inv.id,
            "business_manager_id": inv.business_manager_id,
            "reminder_type": ReminderType.DUE_TODAY.value,
            "priority": ReminderPriority.HIGH.value,
            "reminder_status": ReminderStatus.OPEN.value,
            "due_amount": due_amount,
            "due_date": inv.due_date,
            "next_followup_date": inv.due_date,
            "auto_generated": True,
            "notes": "Auto-generated: due today",
        })
    for r in reminders_to_create:
        db.add(RevReminder(**r))
    db.commit()


# ============================================================
# CLIENTS
# ============================================================
class ClientCreate(BaseModel):
    client_name: str
    brand_name: Optional[str] = None
    company_name: Optional[str] = None
    contact_person: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    business_manager_id: Optional[int] = None
    client_status: str = RevClientStatus.ACTIVE.value
    invoice_day: int = 1
    default_due_days: int = 30
    remarks: Optional[str] = None


class ClientUpdate(BaseModel):
    client_name: Optional[str] = None
    brand_name: Optional[str] = None
    company_name: Optional[str] = None
    contact_person: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    business_manager_id: Optional[int] = None
    client_status: Optional[str] = None
    invoice_day: Optional[int] = None
    default_due_days: Optional[int] = None
    remarks: Optional[str] = None


@router.get("/clients")
def list_clients(search: Optional[str] = None, status: Optional[str] = None, bm: Optional[int] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    q = db.query(RevClient)
    q = _bm_client_filter(q, user)
    if search:
        q = q.filter(RevClient.client_name.ilike(f"%{search}%"))
    if status:
        q = q.filter(RevClient.client_status == status)
    if bm:
        q = q.filter(RevClient.business_manager_id == bm)
    rows = q.order_by(RevClient.client_name).all()
    # Build unified view by joining central accounts
    result = []
    for rc in rows:
        account = db.query(Account).filter(
            or_(
                Account.rev_client_id == rc.id,
                Account.id == rc.account_id,
            )
        ).first()
        result.append(_client_view_dict(rc, account))
    return result


class ClientBillingQuickUpdate(BaseModel):
    client_status: Optional[str] = None
    invoice_day: Optional[int] = None
    default_due_days: Optional[int] = None


@router.put("/clients/{client_id}/billing")
def update_client_billing(
    client_id: int,
    req: ClientBillingQuickUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
):
    """Quick edit of billing-only fields from RevenueOps. Updates the linked central
    Account and keeps RevClient in sync for legacy invoice/payment lookups.
    """
    _check_rev_role(user, ["admin", "finance", "business_manager"])
    c = db.query(RevClient).filter(RevClient.id == client_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    if user.rev_role == "business_manager" and c.business_manager_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    account = db.query(Account).filter(
        or_(
            Account.rev_client_id == c.id,
            Account.id == c.account_id,
        )
    ).first()

    old = json.dumps(c.to_dict())
    if req.client_status is not None:
        normalized = (req.client_status or "Active").lower().replace(" ", "_")
        c.client_status = normalized
        if account:
            account.client_status = req.client_status or "Active"
    if req.invoice_day is not None:
        c.invoice_day = req.invoice_day
        if account:
            account.invoice_day = req.invoice_day
    if req.default_due_days is not None:
        c.default_due_days = req.default_due_days
        if account:
            account.payment_due_days = req.default_due_days

    db.commit()
    db.refresh(c)
    _audit(db, user.id, "update_client_billing", "client", c.id, old_val=old, new_val=json.dumps(c.to_dict()))
    # Central activity log
    client_name, acc_id, acc_name = _client_name_for_log(db, c.id)
    changes = []
    if req.client_status is not None:
        changes.append(f"status → {req.client_status}")
    if req.invoice_day is not None:
        changes.append(f"invoice_day → {req.invoice_day}")
    if req.default_due_days is not None:
        changes.append(f"due_days → {req.default_due_days}")
    log_activity(
        module="RevenueOps",
        action="Client Updated",
        description=f"Updated client {client_name} — {', '.join(changes) or 'billing details'}",
        user_id=user.id,
        user_name=user.full_name or user.email,
        account_id=acc_id,
        account_name=acc_name,
        entity_type="account",
        entity_id=str(c.id),
        details={"client_id": c.id, "changes": changes},
        db=db,
    )
    return _client_view_dict(c, account)


@router.get("/clients/{client_id}")
def get_client(client_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    c = db.query(RevClient).filter(RevClient.id == client_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    if user.rev_role == "business_manager" and c.business_manager_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    account = db.query(Account).filter(
        or_(
            Account.rev_client_id == c.id,
            Account.id == c.account_id,
        )
    ).first()
    return _client_view_dict(c, account)


@router.post("/clients")
def create_client(req: ClientCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    _check_rev_role(user, ["admin", "finance"])
    c = RevClient(**req.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    _audit(db, user.id, "create_client", "client", c.id, new_val=json.dumps(c.to_dict()))
    return c.to_dict()


@router.put("/clients/{client_id}")
def update_client(client_id: int, req: ClientUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    _check_rev_role(user, ["admin", "finance"])
    c = db.query(RevClient).filter(RevClient.id == client_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    old = json.dumps(c.to_dict())
    for k, v in req.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    _audit(db, user.id, "update_client", "client", c.id, old_val=old, new_val=json.dumps(c.to_dict()))
    return c.to_dict()


@router.delete("/clients/{client_id}")
def delete_client(client_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    if user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin can delete clients")
    c = db.query(RevClient).filter(RevClient.id == client_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    old = json.dumps(c.to_dict())
    db.delete(c)
    db.commit()
    _audit(db, user.id, "delete_client", "client", client_id, old_val=old)
    return {"status": "success"}


@router.get("/business-managers")
def list_business_managers(db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """List users with rev_role business_manager for dropdowns."""
    bms = db.query(User).filter(User.rev_role == RevRole.BUSINESS_MANAGER.value, User.is_active == True).all()
    return [{"id": b.id, "name": b.full_name or b.email, "email": b.email, "mobile": b.mobile} for b in bms]


class BMCreate(BaseModel):
    full_name: str
    email: str
    mobile: Optional[str] = None
    password: Optional[str] = None


@router.post("/business-managers")
def create_business_manager(req: BMCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin can create business managers")
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    from backend.routes.auth import get_password_hash
    user = User(
        email=req.email,
        full_name=req.full_name,
        mobile=req.mobile,
        rev_role=RevRole.BUSINESS_MANAGER.value,
        access_revenueops=True,
        hashed_password=get_password_hash(req.password or "changeme123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.delete("/business-managers/{bm_id}")
def delete_business_manager(bm_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin can delete business managers")
    user = db.query(User).filter(User.id == bm_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"status": "success"}


# ============================================================
# BILLING MODELS
# ============================================================
class BillingModelCreate(BaseModel):
    client_id: int
    billing_model_type: str
    amount: float = 0.0
    percentage: Optional[float] = None
    media_spend_linked: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    billing_frequency: str = BillingFrequency.MONTHLY.value
    remarks: Optional[str] = None


class BillingModelUpdate(BaseModel):
    billing_model_type: Optional[str] = None
    amount: Optional[float] = None
    percentage: Optional[float] = None
    media_spend_linked: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    billing_frequency: Optional[str] = None
    remarks: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/billing-models")
def list_billing_models(client_id: Optional[int] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    q = db.query(ClientBillingModel)
    if client_id:
        q = q.filter(ClientBillingModel.client_id == client_id)
    return [bm.to_dict() for bm in q.all()]


@router.post("/billing-models")
def create_billing_model(req: BillingModelCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    _check_rev_role(user, ["admin", "finance"])
    bm = ClientBillingModel(**req.model_dump())
    db.add(bm)
    db.commit()
    db.refresh(bm)
    _audit(db, user.id, "create_billing_model", "billing_model", bm.id, new_val=json.dumps(bm.to_dict()))
    return bm.to_dict()


@router.put("/billing-models/{bm_id}")
def update_billing_model(bm_id: int, req: BillingModelUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    _check_rev_role(user, ["admin", "finance"])
    bm = db.query(ClientBillingModel).filter(ClientBillingModel.id == bm_id).first()
    if not bm:
        raise HTTPException(status_code=404, detail="Billing model not found")
    for k, v in req.model_dump(exclude_unset=True).items():
        setattr(bm, k, v)
    db.commit()
    db.refresh(bm)
    return bm.to_dict()


@router.delete("/billing-models/{bm_id}")
def delete_billing_model(bm_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    if user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin can delete billing models")
    bm = db.query(ClientBillingModel).filter(ClientBillingModel.id == bm_id).first()
    if not bm:
        raise HTTPException(status_code=404, detail="Billing model not found")
    db.delete(bm)
    db.commit()
    return {"status": "success"}


# ============================================================
# INVOICES
# ============================================================
class InvoiceCreate(BaseModel):
    client_id: int
    business_manager_id: Optional[int] = None
    billing_type: Optional[str] = None
    invoice_number: str
    invoice_date: str
    invoice_period: Optional[str] = None
    invoice_amount: float
    due_date: Optional[str] = None
    invoice_status: str = InvoiceStatus.NOT_RAISED.value
    payment_status: str = PaymentStatus.UNPAID.value
    remarks: Optional[str] = None
    # AI invoice upload fields (all optional, additive)
    base_amount: Optional[float] = None
    gst_amount: Optional[float] = None
    cgst_amount: Optional[float] = None
    sgst_amount: Optional[float] = None
    igst_amount: Optional[float] = None
    description: Optional[str] = None
    jobcard_number: Optional[str] = None
    po_reference: Optional[str] = None
    document_file_path: Optional[str] = None
    source: str = "manual"


class InvoiceUpdate(BaseModel):
    client_id: Optional[int] = None
    business_manager_id: Optional[int] = None
    billing_type: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    invoice_period: Optional[str] = None
    invoice_amount: Optional[float] = None
    due_date: Optional[str] = None
    invoice_status: Optional[str] = None
    payment_status: Optional[str] = None
    remarks: Optional[str] = None


def _recalc_invoice(inv: RevInvoice, db: Session):
    total_paid = sum(p.amount for p in inv.payments)
    inv.amount_received = round(total_paid, 2)
    inv.outstanding_amount = round(inv.invoice_amount - total_paid, 2)
    today = date.today()
    if inv.due_date:
        try:
            due = datetime.strptime(inv.due_date, "%Y-%m-%d").date()
            if due < today and inv.outstanding_amount > 0:
                inv.overdue_days = (today - due).days
                if inv.payment_status not in (PaymentStatus.PAID.value, PaymentStatus.CANCELLED.value):
                    inv.invoice_status = InvoiceStatus.OVERDUE.value
                    inv.payment_status = PaymentStatus.OVERDUE.value
            else:
                inv.overdue_days = 0
        except Exception:
            pass
    if inv.outstanding_amount <= 0 and inv.invoice_amount > 0:
        inv.payment_status = PaymentStatus.PAID.value
        if inv.invoice_status not in (InvoiceStatus.CANCELLED.value, InvoiceStatus.CREDIT_NOTE_ISSUED.value):
            inv.invoice_status = InvoiceStatus.PAID.value
    elif total_paid > 0 and inv.outstanding_amount > 0:
        if inv.invoice_status not in (InvoiceStatus.OVERDUE.value, InvoiceStatus.CANCELLED.value, InvoiceStatus.DISPUTED.value, InvoiceStatus.CREDIT_NOTE_ISSUED.value):
            inv.payment_status = PaymentStatus.PARTIALLY_PAID.value
            inv.invoice_status = InvoiceStatus.PARTIALLY_PAID.value
    elif total_paid == 0 and inv.invoice_amount > 0:
        if inv.invoice_status not in (InvoiceStatus.OVERDUE.value, InvoiceStatus.CANCELLED.value, InvoiceStatus.DISPUTED.value, InvoiceStatus.CREDIT_NOTE_ISSUED.value):
            inv.payment_status = PaymentStatus.UNPAID.value
    db.commit()


@router.get("/invoices")
def list_invoices(
    client_id: Optional[int] = None,
    status: Optional[str] = None,
    payment_status: Optional[str] = None,
    bm: Optional[int] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
):
    q = db.query(RevInvoice)
    if user.rev_role == "business_manager":
        bm_clients = db.query(RevClient.id).filter(RevClient.business_manager_id == user.id).subquery()
        q = q.filter(RevInvoice.client_id.in_(bm_clients))
    if client_id:
        q = q.filter(RevInvoice.client_id == client_id)
    if status:
        q = q.filter(RevInvoice.invoice_status == status)
    if payment_status:
        q = q.filter(RevInvoice.payment_status == payment_status)
    if bm:
        q = q.filter(RevInvoice.business_manager_id == bm)
    if search:
        q = q.filter(RevInvoice.invoice_number.ilike(f"%{search}%"))
    if date_from:
        q = q.filter(RevInvoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(RevInvoice.invoice_date <= date_to)
    results = q.order_by(RevInvoice.invoice_date.desc()).all()
    for inv in results:
        _recalc_invoice(inv, db)
    return [inv.to_dict() for inv in results]


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    inv = db.query(RevInvoice).filter(RevInvoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if user.rev_role == "business_manager" and inv.business_manager_id != user.id:
        c = db.query(RevClient).filter(RevClient.id == inv.client_id).first()
        if c and c.business_manager_id != user.id:
            raise HTTPException(status_code=403, detail="Access denied")
    _recalc_invoice(inv, db)
    return inv.to_dict()


@router.post("/invoices")
def create_invoice(req: InvoiceCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    _check_rev_role(user, ["admin", "finance"])
    existing = db.query(RevInvoice).filter(RevInvoice.invoice_number == req.invoice_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Invoice number already exists")
    if req.invoice_amount <= 0:
        raise HTTPException(status_code=400, detail="Invoice amount must be greater than 0")
    bm_id = req.business_manager_id
    if not bm_id:
        c = db.query(RevClient).filter(RevClient.id == req.client_id).first()
        bm_id = c.business_manager_id if c else None
    inv = RevInvoice(
        client_id=req.client_id,
        business_manager_id=bm_id,
        billing_type=req.billing_type,
        invoice_number=req.invoice_number,
        invoice_date=req.invoice_date,
        invoice_period=req.invoice_period,
        invoice_amount=req.invoice_amount,
        due_date=req.due_date,
        invoice_status=req.invoice_status,
        payment_status=req.payment_status,
        outstanding_amount=req.invoice_amount,
        remarks=req.remarks,
        created_by=user.id,
        base_amount=req.base_amount,
        gst_amount=req.gst_amount,
        cgst_amount=req.cgst_amount,
        sgst_amount=req.sgst_amount,
        igst_amount=req.igst_amount,
        description=req.description,
        jobcard_number=req.jobcard_number,
        po_reference=req.po_reference,
        document_file_path=req.document_file_path,
        source=req.source or "manual",
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    _recalc_invoice(inv, db)
    _generate_invoice_reminders(inv, db)
    _audit(db, user.id, "create_invoice", "invoice", inv.id, new_val=json.dumps(inv.to_dict()))
    # Central activity log
    client_name, acc_id, acc_name = _client_name_for_log(db, inv.client_id)
    log_activity(
        module="RevenueOps",
        action="Invoice Created",
        description=f"Created invoice {inv.invoice_number} for {client_name} — INR {inv.invoice_amount:,.2f}",
        user_id=user.id,
        user_name=user.full_name or user.email,
        account_id=acc_id,
        account_name=acc_name,
        entity_type="invoice",
        entity_id=str(inv.id),
        details={"invoice_number": inv.invoice_number, "amount": inv.invoice_amount, "source": req.source},
        db=db,
    )
    # Step 6: auto-link uploaded file to Documents section
    if req.source == "ai_upload" and req.document_file_path:
        try:
            import logging
            logging.getLogger("AdOptima").info(f"Auto-linking document for invoice {inv.id}")
            doc = RevDocument(
                client_id=req.client_id,
                invoice_id=inv.id,
                document_type=DocType.INVOICE_PDF.value,
                document_name=req.document_file_path,
                file_url=req.document_file_path,
                uploaded_by=user.id,
                remarks="Auto-linked from AI invoice upload",
            )
            db.add(doc)
            db.commit()
            _audit(db, user.id, "create_document", "document", doc.id, new_val=json.dumps(doc.to_dict()))
        except Exception as de:
            import logging
            logging.getLogger("AdOptima").warning(f"Auto-link document failed: {de}")
    return inv.to_dict()


# ============================================================
# AI INVOICE UPLOAD (Gemini 2.5 Flash extraction)
# ============================================================
INVOICE_UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "uploads", "invoices",
)

INVOICE_EXTRACT_PROMPT = (
    "You are an invoice data extraction assistant. "
    "Analyze this invoice and extract the following fields. "
    "Return ONLY a valid JSON object with these exact keys, no additional text:\n\n"
    "{\n"
    "  \"invoice_number\": \"the invoice/bill number\",\n"
    "  \"client_name\": \"the buyer/client company name\",\n"
    "  \"contact_person\": \"the Kind Attn / attention person name\",\n"
    "  \"invoice_date\": \"date in YYYY-MM-DD format\",\n"
    "  \"base_amount\": numeric value of taxable amount before tax,\n"
    "  \"cgst_amount\": numeric value of CGST,\n"
    "  \"sgst_amount\": numeric value of SGST,\n"
    "  \"igst_amount\": numeric value of IGST,\n"
    "  \"total_tax\": numeric value of total tax amount,\n"
    "  \"total_amount\": numeric value of total amount after tax,\n"
    "  \"description\": \"description of services from the line items\",\n"
    "  \"jobcard_number\": \"job card number if present, else null\",\n"
    "  \"po_reference\": \"PO reference if present, else null\",\n"
    "  \"client_gstin\": \"client GSTIN number if present, else null\",\n"
    "  \"state\": \"client state if present, else null\",\n"
    "  \"state_code\": \"client state code if present, else null\"\n"
    "}\n\n"
    "Rules:\n"
    "- All amount fields must be numbers, not strings\n"
    "- Date must be in YYYY-MM-DD format\n"
    "- If a field is not found on the invoice, set it to null\n"
    "- Do not guess or infer — only extract what is visible"
)

ALLOWED_INVOICE_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
}
ALLOWED_INVOICE_EXTS = {".pdf", ".jpg", ".jpeg", ".png"}


def _clean_gemini_json(text_resp):
    """Strip markdown fences and leading/trailing whitespace from a model response."""
    if not text_resp:
        return ""
    s = text_resp.strip()
    if s.startswith("```"):
        # remove opening fence (optionally with language tag)
        s = s.split("\n", 1)[1] if "\n" in s else s
        # remove closing fence
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    return s


def _match_client_account(db, extracted_name):
    """Try to match the extracted client name to a central Account row.

    Strategy:
      1. Exact match on Account.name or Account.brand_name (case-insensitive)
      2. Partial match: extracted name CONTAINS account name, or account name
         CONTAINS extracted name (case-insensitive)
    Returns (account, account_rev_client_id) or (None, None).
    """
    if not extracted_name:
        return None, None
    name_norm = extracted_name.strip().lower()
    accounts = db.query(Account).all()
    # 1. Exact
    for a in accounts:
        if a.name and a.name.strip().lower() == name_norm:
            return a, a.rev_client_id
        if a.brand_name and a.brand_name.strip().lower() == name_norm:
            return a, a.rev_client_id
    # 2. Partial / fuzzy (containment both ways)
    for a in accounts:
        an = (a.name or "").strip().lower()
        bn = (a.brand_name or "").strip().lower()
        if not an and not bn:
            continue
        if (an and (an in name_norm or name_norm in an)) or \
           (bn and (bn in name_norm or name_norm in bn)):
            return a, a.rev_client_id
    return None, None


def _compute_suggested_due_date(invoice_date, due_days):
    """Return YYYY-MM-DD = invoice_date + due_days. Falls back to +45."""
    if not invoice_date:
        return None
    days = due_days if due_days and due_days > 0 else 45
    try:
        d = datetime.strptime(invoice_date, "%Y-%m-%d").date()
    except Exception:
        return None
    from datetime import timedelta
    return (d + timedelta(days=days)).isoformat()


@router.post("/invoices/upload")
async def upload_invoice_extract(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
):
    """Upload an invoice PDF/image and extract fields with Gemini 2.5 Flash.
    Does NOT save any invoice — returns extracted data for user review.
    """
    # Validate file type
    original_name = file.filename or "upload"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in ALLOWED_INVOICE_EXTS:
        raise HTTPException(status_code=400, detail="Unsupported file type. Allowed: PDF, JPEG, PNG.")

    # Ensure upload dir exists
    os.makedirs(INVOICE_UPLOAD_DIR, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    saved_name = f"{timestamp}_{original_name}"
    saved_path = os.path.join(INVOICE_UPLOAD_DIR, saved_name)

    # Save uploaded file
    try:
        contents = await file.read()
        with open(saved_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {e}")

    # Send to Gemini 2.5 Flash
    try:
        from google import genai
        from google.genai import types
        client = genai.Client()

        # Build the file part based on content type
        if ext == ".pdf":
            mime = "application/pdf"
            inline_part = types.Part.from_bytes(data=contents, mime_type=mime)
        elif ext in (".jpg", ".jpeg"):
            mime = "image/jpeg"
            inline_part = types.Part.from_bytes(data=contents, mime_type=mime)
        else:
            mime = "image/png"
            inline_part = types.Part.from_bytes(data=contents, mime_type=mime)

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[inline_part, INVOICE_EXTRACT_PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                system_instruction="You are an invoice data extraction assistant. Return only JSON.",
            ),
        )
        raw_text = response.text if hasattr(response, "text") else ""
    except Exception as e:
        # Clean up file on extraction failure? Keep it so user can retry, but report error.
        raise HTTPException(status_code=500, detail=f"Gemini extraction failed: {e}")

    # Parse the JSON response (clean fences if present)
    extracted = None
    parse_error = None
    try:
        cleaned = _clean_gemini_json(raw_text)
        extracted = json.loads(cleaned)
    except Exception as e1:
        parse_error = str(e1)
        # Retry once more after aggressive cleaning
        try:
            import re
            cleaned = re.sub(r"^```(?:json)?|```$", "", raw_text or "", flags=re.MULTILINE).strip()
            extracted = json.loads(cleaned)
        except Exception as e2:
            parse_error = f"{e1} | retry: {e2}"

    if extracted is None:
        raise HTTPException(
            status_code=422,
            detail=f"Could not parse Gemini response as JSON. {parse_error or ''} Raw: {(raw_text or '')[:300]}",
        )

    # Match client account
    client_name = extracted.get("client_name")
    matched_account, matched_rev_client_id = _match_client_account(db, client_name)

    # Compute suggested due date
    invoice_date = extracted.get("invoice_date")
    due_days = None
    if matched_account:
        due_days = matched_account.payment_due_days
    suggested_due = _compute_suggested_due_date(invoice_date, due_days)

    # Suggested BM
    suggested_bm_name = None
    if matched_account and matched_account.business_manager_id:
        bm_user = db.query(User).filter(User.id == matched_account.business_manager_id).first()
        if bm_user:
            suggested_bm_name = bm_user.full_name or bm_user.email

    return {
        "success": True,
        "extracted_data": extracted,
        "matched_account": {
            "id": matched_account.id if matched_account else None,
            "name": matched_account.name if matched_account else None,
            "rev_client_id": matched_rev_client_id if matched_account else None,
        },
        "suggested_due_date": suggested_due,
        "suggested_bm": suggested_bm_name,
        "suggested_bm_id": matched_account.business_manager_id if matched_account else None,
        "file_path": saved_name,
    }


@router.put("/invoices/{invoice_id}")
def update_invoice(invoice_id: int, req: InvoiceUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    _check_rev_role(user, ["admin", "finance"])
    inv = db.query(RevInvoice).filter(RevInvoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    old = json.dumps(inv.to_dict())
    for k, v in req.model_dump(exclude_unset=True).items():
        setattr(inv, k, v)
    db.commit()
    db.refresh(inv)
    _recalc_invoice(inv, db)
    _generate_invoice_reminders(inv, db)
    _audit(db, user.id, "update_invoice", "invoice", inv.id, old_val=old, new_val=json.dumps(inv.to_dict()))
    # Central activity log
    client_name, acc_id, acc_name = _client_name_for_log(db, inv.client_id)
    status_change = req.invoice_status or req.payment_status
    log_activity(
        module="RevenueOps",
        action="Invoice Updated",
        description=f"Updated invoice {inv.invoice_number} status to {status_change or 'updated'}",
        user_id=user.id,
        user_name=user.full_name or user.email,
        account_id=acc_id,
        account_name=acc_name,
        entity_type="invoice",
        entity_id=str(inv.id),
        details={"invoice_number": inv.invoice_number, "status_change": status_change, "changes": req.model_dump(exclude_unset=True)},
        db=db,
    )
    return inv.to_dict()


@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    if user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin can delete invoices")
    inv = db.query(RevInvoice).filter(RevInvoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    db.query(RevPayment).filter(RevPayment.invoice_id == invoice_id).delete()
    db.delete(inv)
    db.commit()
    _audit(db, user.id, "delete_invoice", "invoice", invoice_id)
    return {"status": "success"}


# ============================================================
# PAYMENTS
# ============================================================
class PaymentCreate(BaseModel):
    invoice_id: int
    client_id: int
    payment_date: str
    amount: float
    payment_mode: str = PaymentMode.BANK_TRANSFER.value
    reference_number: Optional[str] = None
    payment_proof_url: Optional[str] = None
    remarks: Optional[str] = None


class PaymentUpdate(BaseModel):
    amount: Optional[float] = None
    payment_date: Optional[str] = None
    payment_mode: Optional[str] = None
    reference_number: Optional[str] = None
    remarks: Optional[str] = None


@router.get("/payments")
def list_payments(
    client_id: Optional[int] = None,
    invoice_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
):
    q = db.query(RevPayment)
    if user.rev_role == "business_manager":
        bm_clients = db.query(RevClient.id).filter(RevClient.business_manager_id == user.id).subquery()
        q = q.filter(RevPayment.client_id.in_(bm_clients))
    if client_id:
        q = q.filter(RevPayment.client_id == client_id)
    if invoice_id:
        q = q.filter(RevPayment.invoice_id == invoice_id)
    if date_from:
        q = q.filter(RevPayment.payment_date >= date_from)
    if date_to:
        q = q.filter(RevPayment.payment_date <= date_to)
    return [p.to_dict() for p in q.order_by(RevPayment.payment_date.desc()).all()]


@router.post("/payments")
def create_payment(req: PaymentCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    _check_rev_role(user, ["admin", "finance"])
    inv = db.query(RevInvoice).filter(RevInvoice.id == req.invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    total_paid = sum(p.amount for p in inv.payments)
    outstanding = inv.invoice_amount - total_paid
    if req.amount > outstanding + 0.01 and user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=400, detail=f"Payment ({req.amount}) exceeds outstanding amount ({round(outstanding, 2)})")
    p = RevPayment(
        invoice_id=req.invoice_id,
        client_id=req.client_id,
        payment_date=req.payment_date,
        amount=req.amount,
        payment_mode=req.payment_mode,
        reference_number=req.reference_number,
        payment_proof_url=req.payment_proof_url,
        remarks=req.remarks,
        created_by=user.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    _recalc_invoice(inv, db)
    _audit(db, user.id, "create_payment", "payment", p.id, new_val=json.dumps(p.to_dict()))
    # Central activity log
    client_name, acc_id, acc_name = _client_name_for_log(db, p.client_id)
    log_activity(
        module="RevenueOps",
        action="Payment Recorded",
        description=f"Recorded payment of INR {p.amount:,.2f} for {client_name}",
        user_id=user.id,
        user_name=user.full_name or user.email,
        account_id=acc_id,
        account_name=acc_name,
        entity_type="payment",
        entity_id=str(p.id),
        details={"invoice_id": p.invoice_id, "amount": p.amount, "payment_mode": p.payment_mode},
        db=db,
    )
    return p.to_dict()


@router.put("/payments/{payment_id}")
def update_payment(payment_id: int, req: PaymentUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    _check_rev_role(user, ["admin", "finance"])
    p = db.query(RevPayment).filter(RevPayment.id == payment_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Payment not found")
    for k, v in req.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    inv = db.query(RevInvoice).filter(RevInvoice.id == p.invoice_id).first()
    if inv:
        _recalc_invoice(inv, db)
    return p.to_dict()


@router.delete("/payments/{payment_id}")
def delete_payment(payment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    if user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin can delete payments")
    p = db.query(RevPayment).filter(RevPayment.id == payment_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Payment not found")
    inv_id = p.invoice_id
    db.delete(p)
    db.commit()
    inv = db.query(RevInvoice).filter(RevInvoice.id == inv_id).first()
    if inv:
        _recalc_invoice(inv, db)
    return {"status": "success"}


# ============================================================
# DOCUMENTS
# ============================================================
class DocumentCreate(BaseModel):
    client_id: int
    invoice_id: Optional[int] = None
    document_type: str = DocType.OTHER.value
    document_name: str
    file_url: Optional[str] = None
    remarks: Optional[str] = None


@router.get("/documents")
def list_documents(client_id: Optional[int] = None, invoice_id: Optional[int] = None, doc_type: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    q = db.query(RevDocument)
    if user.rev_role == "business_manager":
        bm_clients = db.query(RevClient.id).filter(RevClient.business_manager_id == user.id).subquery()
        q = q.filter(RevDocument.client_id.in_(bm_clients))
    if client_id:
        q = q.filter(RevDocument.client_id == client_id)
    if invoice_id:
        q = q.filter(RevDocument.invoice_id == invoice_id)
    if doc_type:
        q = q.filter(RevDocument.document_type == doc_type)
    return [d.to_dict() for d in q.order_by(RevDocument.created_at.desc()).all()]


@router.post("/documents")
def create_document(req: DocumentCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    _check_rev_role(user, ["admin", "finance"])
    d = RevDocument(**req.model_dump(), uploaded_by=user.id)
    db.add(d)
    db.commit()
    db.refresh(d)
    _audit(db, user.id, "upload_document", "document", d.id, new_val=json.dumps(d.to_dict()))
    return d.to_dict()


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    if user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin can delete documents")
    d = db.query(RevDocument).filter(RevDocument.id == doc_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(d)
    db.commit()
    return {"status": "success"}


# ============================================================
# REMINDERS
# ============================================================
class ReminderCreate(BaseModel):
    client_id: int
    invoice_id: Optional[int] = None
    business_manager_id: Optional[int] = None
    reminder_type: str
    priority: str = ReminderPriority.MEDIUM.value
    due_amount: float = 0.0
    due_date: Optional[str] = None
    next_followup_date: Optional[str] = None
    notes: Optional[str] = None


class ReminderUpdate(BaseModel):
    reminder_status: Optional[str] = None
    priority: Optional[str] = None
    next_followup_date: Optional[str] = None
    last_followup_date: Optional[str] = None
    notes: Optional[str] = None


class ReminderSnooze(BaseModel):
    value: int
    unit: str  # hour or day


@router.get("/reminders")
def list_reminders(status: Optional[str] = None, priority: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    q = db.query(RevReminder)
    if user.rev_role == "business_manager":
        q = q.filter(RevReminder.business_manager_id == user.id)
    if status:
        q = q.filter(RevReminder.reminder_status == status)
    if priority:
        q = q.filter(RevReminder.priority == priority)
    return [r.to_dict() for r in q.order_by(RevReminder.created_at.desc()).all()]


@router.get("/reminders/due-today")
def due_reminders(db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """Return reminders whose next_followup_date is today or earlier and not snoozed/done."""
    today = date.today().isoformat()
    q = db.query(RevReminder).filter(
        RevReminder.reminder_status != ReminderStatus.DONE.value,
        RevReminder.next_followup_date <= today,
        or_(RevReminder.snooze_until == None, RevReminder.snooze_until <= today),
    )
    if user.rev_role == "business_manager":
        q = q.filter(RevReminder.business_manager_id == user.id)
    return [r.to_dict() for r in q.order_by(RevReminder.priority.desc(), RevReminder.created_at.desc()).all()]


@router.post("/reminders/{reminder_id}/snooze")
def snooze_reminder(reminder_id: int, req: ReminderSnooze, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    r = db.query(RevReminder).filter(RevReminder.id == reminder_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Reminder not found")
    if user.rev_role == "business_manager" and r.business_manager_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    now = datetime.utcnow()
    delta = __import__("datetime").timedelta(hours=req.value) if req.unit == "hour" else __import__("datetime").timedelta(days=req.value)
    snooze_until = (now + delta).isoformat()
    r.snooze_until = snooze_until
    r.reminder_status = ReminderStatus.SNOOZED.value
    db.commit()
    db.refresh(r)
    return r.to_dict()


@router.post("/reminders")
def create_reminder(req: ReminderCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    bm_id = req.business_manager_id
    if not bm_id and user.rev_role == "business_manager":
        bm_id = user.id
    r = RevReminder(**req.model_dump(), business_manager_id=bm_id)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r.to_dict()


@router.put("/reminders/{reminder_id}")
def update_reminder(reminder_id: int, req: ReminderUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    r = db.query(RevReminder).filter(RevReminder.id == reminder_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Reminder not found")
    if user.rev_role == "business_manager" and r.business_manager_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    for k, v in req.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    db.commit()
    db.refresh(r)
    return r.to_dict()


@router.delete("/reminders/{reminder_id}")
def delete_reminder(reminder_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    if user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin can delete reminders")
    r = db.query(RevReminder).filter(RevReminder.id == reminder_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Reminder not found")
    db.delete(r)
    db.commit()
    return {"status": "success"}


@router.post("/reminders/{reminder_id}/generate-text")
def generate_reminder_text(reminder_id: int, channel: str = "whatsapp", db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    r = db.query(RevReminder).filter(RevReminder.id == reminder_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Reminder not found")
    client = db.query(RevClient).filter(RevClient.id == r.client_id).first()
    inv = db.query(RevInvoice).filter(RevInvoice.id == r.invoice_id).first() if r.invoice_id else None
    client_name = client.client_name if client else "Client"
    inv_num = inv.invoice_number if inv else "N/A"
    amount = r.due_amount or (inv.outstanding_amount if inv and inv.outstanding_amount else 0)
    overdue = r.overdue_days if hasattr(r, 'overdue_days') else 0

    if channel == "whatsapp":
        if overdue and overdue > 15:
            text = f"Hi {client_name}, invoice {inv_num} for INR {amount:,.2f} has been overdue for {overdue} days. Request you to please prioritize the payment or confirm the expected payment date today."
        else:
            text = f"Hi {client_name}, this is a gentle reminder that invoice {inv_num} for INR {amount:,.2f} is currently due. Request you to please share the payment update. Thank you."
    else:
        text = f"Dear {client_name},\n\nThis is to remind you that invoice {inv_num} for INR {amount:,.2f} is currently pending. Kindly arrange for payment at your earliest convenience.\n\nRegards,\nRevenue Team"

    return {"text": text, "channel": channel, "client_name": client_name, "invoice_number": inv_num, "amount": amount}


# ============================================================
# FOLLOWUP NOTES
# ============================================================
class FollowupCreate(BaseModel):
    client_id: int
    invoice_id: Optional[int] = None
    note: str
    next_followup_date: Optional[str] = None


@router.get("/followup-notes")
def list_followup_notes(client_id: Optional[int] = None, invoice_id: Optional[int] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    q = db.query(FollowupNote)
    if user.rev_role == "business_manager":
        q = q.filter(FollowupNote.business_manager_id == user.id)
    if client_id:
        q = q.filter(FollowupNote.client_id == client_id)
    if invoice_id:
        q = q.filter(FollowupNote.invoice_id == invoice_id)
    return [n.to_dict() for n in q.order_by(FollowupNote.created_at.desc()).all()]


@router.post("/followup-notes")
def create_followup_note(req: FollowupCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    n = FollowupNote(
        client_id=req.client_id,
        invoice_id=req.invoice_id,
        note=req.note,
        next_followup_date=req.next_followup_date,
        business_manager_id=user.id if user.rev_role == "business_manager" else None,
        created_by=user.id,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return n.to_dict()


# ============================================================
# OUTSTANDING
# ============================================================
@router.get("/outstanding")
def list_outstanding(
    client_id: Optional[int] = None,
    bm: Optional[int] = None,
    ageing: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
):
    q = db.query(RevInvoice).filter(RevInvoice.outstanding_amount > 0)
    if user.rev_role == "business_manager":
        bm_clients = db.query(RevClient.id).filter(RevClient.business_manager_id == user.id).subquery()
        q = q.filter(RevInvoice.client_id.in_(bm_clients))
    if client_id:
        q = q.filter(RevInvoice.client_id == client_id)
    if bm:
        q = q.filter(RevInvoice.business_manager_id == bm)
    results = q.all()
    for inv in results:
        _recalc_invoice(inv, db)
    db.commit()

    items = [inv.to_dict() for inv in results]
    if ageing:
        today = date.today()
        filtered = []
        for it in items:
            od = it.get("overdue_days", 0)
            if ageing == "due_in_3_days" and od <= 3 and od >= -3:
                filtered.append(it)
            elif ageing == "due_today" and od == 0:
                filtered.append(it)
            elif ageing == "1_7" and 1 <= od <= 7:
                filtered.append(it)
            elif ageing == "8_15" and 8 <= od <= 15:
                filtered.append(it)
            elif ageing == "16_30" and 16 <= od <= 30:
                filtered.append(it)
            elif ageing == "31_60" and 31 <= od <= 60:
                filtered.append(it)
            elif ageing == "60_plus" and od > 60:
                filtered.append(it)
        items = filtered
    return items


# ============================================================
# DASHBOARD
# ============================================================
@router.get("/dashboard")
def dashboard(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    client_ids: Optional[str] = None,
    bm: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
):
    # Build visible-client subquery based on role/assignments.
    visible_client_ids = None
    if user.role not in ("admin", "superadmin"):
        if user.rev_role == "business_manager":
            visible_client_ids = db.query(RevClient.id).filter(
                RevClient.business_manager_id == user.id
            ).subquery()
        elif user.role in ("user", "newuser"):
            assigned_ids = user.assigned_account_ids()
            if not assigned_ids:
                visible_client_ids = db.query(RevClient.id).filter(false()).subquery()
            else:
                visible_client_ids = (
                    db.query(RevClient.id)
                    .join(
                        Account,
                        or_(
                            Account.rev_client_id == RevClient.id,
                            RevClient.account_id == Account.id,
                        ),
                        isouter=False,
                    )
                    .filter(Account.id.in_(assigned_ids))
                    .subquery()
                )
        else:
            visible_client_ids = db.query(RevClient.id).filter(false()).subquery()

    q = db.query(RevInvoice)
    if visible_client_ids is not None:
        q = q.filter(RevInvoice.client_id.in_(visible_client_ids))
    if client_ids:
        # Admin/superadmin only: comma-separated RevClient IDs to scope dashboard.
        try:
            ids = [int(x.strip()) for x in client_ids.split(",") if x.strip()]
            if ids:
                # Extra safety: if non-admin, intersect with visible clients
                if user.role in ("admin", "superadmin"):
                    q = q.filter(RevInvoice.client_id.in_(ids))
                else:
                    q = q.filter(
                        and_(
                            RevInvoice.client_id.in_(ids),
                            RevInvoice.client_id.in_(visible_client_ids),
                        )
                    )
        except ValueError:
            pass
    if bm:
        q = q.filter(RevInvoice.business_manager_id == bm)
    if date_from:
        q = q.filter(RevInvoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(RevInvoice.invoice_date <= date_to)

    invoices = q.all()
    for inv in invoices:
        _recalc_invoice(inv, db)
    db.commit()

    total_billed = sum(inv.invoice_amount for inv in invoices if inv.invoice_status != InvoiceStatus.CANCELLED.value)
    total_collected = sum(sum(p.amount for p in inv.payments) for inv in invoices if inv.invoice_status != InvoiceStatus.CANCELLED.value)
    total_outstanding = round(total_billed - total_collected, 2)
    collection_pct = round((total_collected / total_billed) * 100, 2) if total_billed else 0

    today = date.today()
    this_month_start = today.replace(day=1).isoformat()
    this_month_invoices = [inv for inv in invoices if inv.invoice_date >= this_month_start and inv.invoice_status != InvoiceStatus.CANCELLED.value]
    monthly_billed = sum(inv.invoice_amount for inv in this_month_invoices)
    monthly_collected = sum(sum(p.amount for p in inv.payments) for inv in this_month_invoices)

    overdue_invoices = [inv for inv in invoices if inv.invoice_status in (InvoiceStatus.OVERDUE.value,) or (inv.outstanding_amount and inv.outstanding_amount > 0 and inv.due_date and inv.due_date < today.isoformat())]
    total_overdue = round(sum(inv.outstanding_amount for inv in overdue_invoices), 2)

    clients = db.query(RevClient)
    if visible_client_ids is not None:
        clients = clients.filter(RevClient.id.in_(visible_client_ids))
    all_clients = clients.all()
    active_clients = [c for c in all_clients if c.client_status == RevClientStatus.ACTIVE.value]

    client_ids_with_invoices = set(inv.client_id for inv in invoices if inv.invoice_status not in (InvoiceStatus.CANCELLED.value,))
    clients_no_invoice = [c for c in active_clients if c.id not in client_ids_with_invoices]

    partially_paid = [inv for inv in invoices if inv.invoice_status == InvoiceStatus.PARTIALLY_PAID.value]
    disputed = [inv for inv in invoices if inv.invoice_status == InvoiceStatus.DISPUTED.value]
    cancelled = [inv for inv in invoices if inv.invoice_status == InvoiceStatus.CANCELLED.value]
    credit_notes = [inv for inv in invoices if inv.invoice_status == InvoiceStatus.CREDIT_NOTE_ISSUED.value]

    bms = db.query(User).filter(User.rev_role == RevRole.BUSINESS_MANAGER.value).all()
    bm_stats = []
    for b in bms:
        bm_invs = [inv for inv in invoices if inv.business_manager_id == b.id]
        bm_billed = sum(inv.invoice_amount for inv in bm_invs)
        bm_collected = sum(sum(p.amount for p in inv.payments) for inv in bm_invs)
        bm_outstanding = round(bm_billed - bm_collected, 2)
        bm_overdue = sum(inv.outstanding_amount for inv in bm_invs if inv.invoice_status in (InvoiceStatus.OVERDUE.value,) or (inv.due_date and inv.due_date < today.isoformat() and inv.outstanding_amount and inv.outstanding_amount > 0))
        bm_stats.append({
            "bm_id": b.id, "bm_name": b.full_name or b.email,
            "total_billed": round(bm_billed, 2), "total_collected": round(bm_collected, 2),
            "total_outstanding": bm_outstanding, "total_overdue": round(bm_overdue, 2),
            "collection_pct": round((bm_collected / bm_billed) * 100, 2) if bm_billed else 0,
            "client_count": len(set(inv.client_id for inv in bm_invs)),
        })

    billing_model_dist = {}
    for inv in invoices:
        bt = inv.billing_type or "unspecified"
        billing_model_dist[bt] = billing_model_dist.get(bt, 0) + inv.invoice_amount

    return {
        "total_billed": round(total_billed, 2),
        "total_collected": round(total_collected, 2),
        "total_outstanding": total_outstanding,
        "total_overdue": total_overdue,
        "collection_percentage": collection_pct,
        "monthly_billed": round(monthly_billed, 2),
        "monthly_collected": round(monthly_collected, 2),
        "invoice_count": len(invoices),
        "active_client_count": len(active_clients),
        "clients_no_invoice": len(clients_no_invoice),
        "clients_overdue": len(set(inv.client_id for inv in overdue_invoices)),
        "partially_paid_count": len(partially_paid),
        "disputed_count": len(disputed),
        "cancelled_count": len(cancelled),
        "credit_note_count": len(credit_notes),
        "overdue_invoices": len(overdue_invoices),
        "top_overdue_clients": sorted(
            [{"client_id": inv.client_id, "client_name": inv.client.client_name if inv.client else None, "outstanding": round(inv.outstanding_amount, 2)}
             for inv in overdue_invoices[:10]],
            key=lambda x: x["outstanding"], reverse=True
        ),
        "bm_stats": bm_stats,
        "billing_model_dist": billing_model_dist,
        "expected_collection_week": round(total_outstanding * 0.2, 2),
        "expected_collection_month": round(total_outstanding * 0.5, 2),
    }


# ============================================================
# REPORTS
# ============================================================
@router.get("/reports/monthly-billing")
def report_monthly_billing(year: Optional[int] = None, month: Optional[int] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    q = db.query(RevInvoice)
    if year and month:
        prefix = f"{year}-{month:02d}"
        q = q.filter(RevInvoice.invoice_date.startswith(prefix))
    invoices = q.all()
    for inv in invoices:
        _recalc_invoice(inv, db)
    return [inv.to_dict() for inv in invoices]


@router.get("/reports/outstanding")
def report_outstanding(db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    return list_outstanding(db=db, user=user)


@router.get("/reports/bm-wise")
def report_bm_wise(db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    bms = db.query(User).filter(User.rev_role == RevRole.BUSINESS_MANAGER.value).all()
    result = []
    for b in bms:
        bm_clients = db.query(RevClient).filter(RevClient.business_manager_id == b.id).all()
        client_ids = [c.id for c in bm_clients]
        invs = db.query(RevInvoice).filter(RevInvoice.client_id.in_(client_ids)).all() if client_ids else []
        for inv in invs:
            _recalc_invoice(inv, db)
        billed = sum(inv.invoice_amount for inv in invs)
        collected = sum(sum(p.amount for p in inv.payments) for inv in invs)
        result.append({
            "bm_id": b.id, "bm_name": b.full_name or b.email,
            "client_count": len(bm_clients),
            "total_billed": round(billed, 2), "total_collected": round(collected, 2),
            "total_outstanding": round(billed - collected, 2),
            "overdue_count": len([inv for inv in invs if inv.invoice_status == InvoiceStatus.OVERDUE.value]),
        })
    return result


@router.get("/reports/invoice-not-raised")
def report_invoice_not_raised(db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    clients = db.query(RevClient).filter(RevClient.client_status == RevClientStatus.ACTIVE.value)
    if user.rev_role == "business_manager":
        clients = clients.filter(RevClient.business_manager_id == user.id)
    result = []
    for c in clients.all():
        has_invoice = db.query(RevInvoice).filter(RevInvoice.client_id == c.id, RevInvoice.invoice_status != InvoiceStatus.CANCELLED.value).first()
        if not has_invoice:
            result.append(c.to_dict())
    return result


# ============================================================
# SETTINGS
# ============================================================
@router.get("/settings")
def list_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    settings = db.query(RevSetting).all()
    return {s.key: s.value for s in settings}


class SettingUpdate(BaseModel):
    key: str
    value: str


@router.put("/settings")
def update_setting(req: SettingUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    if user.role not in ("admin", "superadmin") and user.rev_role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can update settings")
    s = db.query(RevSetting).filter(RevSetting.key == req.key).first()
    if s:
        s.value = req.value
    else:
        s = RevSetting(key=req.key, value=req.value)
        db.add(s)
    db.commit()
    db.refresh(s)
    return s.to_dict()


# ============================================================
# AUDIT LOGS
# ============================================================
@router.get("/audit-logs")
def list_audit_logs(entity_type: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    if user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin can view audit logs")
    q = db.query(AuditLog)
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    return [a.to_dict() for a in q.order_by(AuditLog.created_at.desc()).limit(200).all()]


# ============================================================
# SEED DEMO DATA
# ============================================================
@router.post("/seed-demo")
def seed_demo_data(db: Session = Depends(get_db), user: User = Depends(get_current_user_required)):
    """Deprecated — demo seeding is disabled. Create clients manually via the UI."""
    return {"status": "skipped", "message": "Demo data seeding is disabled. Create clients, invoices, and payments manually via the RevenueOps UI."}