"""
Database models for RevenueOps: clients, billing models, invoices, payments,
documents, reminders, followup notes, audit logs, and settings.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, ForeignKey, JSON, Enum as SAEnum
from sqlalchemy.orm import relationship
from backend.db.database import Base
import enum


class RevClientStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"
    ON_HOLD = "on_hold"


class BillingModelType(str, enum.Enum):
    MONTHLY_RETAINER = "monthly_retainer"
    ONE_TIME_PROJECT = "one_time_project"
    PERCENTAGE_MEDIA = "percentage_media"
    FIXED_PLUS_PERCENTAGE = "fixed_plus_percentage"
    CREATIVE_PACKAGE = "creative_package"
    WEBSITE_MILESTONE = "website_milestone"
    PERFORMANCE_INCENTIVE = "performance_incentive"


class BillingFrequency(str, enum.Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ONE_TIME = "one_time"
    MILESTONE = "milestone"


class InvoiceStatus(str, enum.Enum):
    NOT_RAISED = "not_raised"
    INVOICE_RAISED = "invoice_raised"
    SENT_TO_CLIENT = "sent_to_client"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    OVERDUE = "overdue"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"
    CREDIT_NOTE_ISSUED = "credit_note_issued"


class PaymentStatus(str, enum.Enum):
    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    OVERDUE = "overdue"


class PaymentMode(str, enum.Enum):
    BANK_TRANSFER = "bank_transfer"
    UPI = "upi"
    CHEQUE = "cheque"
    CASH = "cash"
    OTHER = "other"


class ReminderType(str, enum.Enum):
    DUE_IN_3_DAYS = "due_in_3_days"
    DUE_IN_2_DAYS = "due_in_2_days"
    DUE_IN_1_DAY = "due_in_1_day"
    DUE_TODAY = "due_today"
    OVERDUE_7_DAYS = "overdue_7_days"
    OVERDUE_15_DAYS = "overdue_15_days"
    OVERDUE_30_DAYS = "overdue_30_days"
    INVOICE_NOT_RAISED = "invoice_not_raised"
    FOLLOWUP_PENDING = "followup_pending"
    PAYMENT_PROMISED = "payment_promised"


class ReminderPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReminderStatus(str, enum.Enum):
    OPEN = "open"
    SNOOZED = "snoozed"
    DONE = "done"


class RevRole(str, enum.Enum):
    ADMIN = "admin"
    FINANCE = "finance"
    BUSINESS_MANAGER = "business_manager"


class DocType(str, enum.Enum):
    INVOICE_PDF = "invoice_pdf"
    PO = "po"
    SOW = "sow"
    AGREEMENT = "agreement"
    PAYMENT_PROOF = "payment_proof"
    CREDIT_NOTE = "credit_note"
    CLIENT_COMMUNICATION = "client_communication"
    OTHER = "other"


class RevClient(Base):
    __tablename__ = "rev_clients"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, nullable=True, index=True)
    client_name = Column(String, nullable=False)
    brand_name = Column(String, nullable=True)
    company_name = Column(String, nullable=True)
    contact_person = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    contact_phone = Column(String, nullable=True)
    business_manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    client_status = Column(String, default=RevClientStatus.ACTIVE.value)
    invoice_day = Column(Integer, default=1)
    default_due_days = Column(Integer, default=30)
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    billing_models = relationship("ClientBillingModel", back_populates="client", lazy="dynamic")
    invoices = relationship("RevInvoice", back_populates="client", lazy="dynamic")
    business_manager = relationship("User", foreign_keys=[business_manager_id])

    def to_dict(self):
        bm = self.business_manager
        return {
            "id": self.id,
            "account_id": self.account_id,
            "client_name": self.client_name,
            "brand_name": self.brand_name,
            "company_name": self.company_name,
            "contact_person": self.contact_person,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "business_manager_id": self.business_manager_id,
            "business_manager_name": bm.full_name or bm.email if bm else None,
            "client_status": self.client_status,
            "invoice_day": self.invoice_day,
            "default_due_days": self.default_due_days,
            "remarks": self.remarks,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ClientBillingModel(Base):
    __tablename__ = "client_billing_models"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("rev_clients.id"), nullable=False)
    billing_model_type = Column(String, nullable=False)
    amount = Column(Float, default=0.0)
    percentage = Column(Float, nullable=True)
    media_spend_linked = Column(Float, nullable=True)
    start_date = Column(String, nullable=True)
    end_date = Column(String, nullable=True)
    billing_frequency = Column(String, default=BillingFrequency.MONTHLY.value)
    remarks = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("RevClient", back_populates="billing_models")

    def to_dict(self):
        return {
            "id": self.id,
            "client_id": self.client_id,
            "billing_model_type": self.billing_model_type,
            "amount": self.amount,
            "percentage": self.percentage,
            "media_spend_linked": self.media_spend_linked,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "billing_frequency": self.billing_frequency,
            "remarks": self.remarks,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RevInvoice(Base):
    __tablename__ = "rev_invoices"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("rev_clients.id"), nullable=False)
    business_manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    billing_type = Column(String, nullable=True)
    invoice_number = Column(String, nullable=False, unique=True)
    invoice_date = Column(String, nullable=False)
    invoice_period = Column(String, nullable=True)
    invoice_amount = Column(Float, default=0.0)
    due_date = Column(String, nullable=True)
    amount_received = Column(Float, default=0.0)
    outstanding_amount = Column(Float, default=0.0)
    invoice_status = Column(String, default=InvoiceStatus.NOT_RAISED.value)
    payment_status = Column(String, default=PaymentStatus.UNPAID.value)
    overdue_days = Column(Integer, default=0)
    remarks = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # AI invoice upload fields (additive, nullable)
    base_amount = Column(Float, nullable=True)
    gst_amount = Column(Float, nullable=True)
    cgst_amount = Column(Float, nullable=True)
    sgst_amount = Column(Float, nullable=True)
    igst_amount = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    jobcard_number = Column(String, nullable=True)
    po_reference = Column(String, nullable=True)
    document_file_path = Column(String, nullable=True)
    source = Column(String, default="manual")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("RevClient", back_populates="invoices")
    payments = relationship("RevPayment", back_populates="invoice", lazy="dynamic")
    documents = relationship("RevDocument", back_populates="invoice", lazy="dynamic")
    reminders = relationship("RevReminder", back_populates="invoice", lazy="dynamic")
    bm = relationship("User", foreign_keys=[business_manager_id])

    def to_dict(self):
        total_paid = sum(p.amount for p in self.payments) if self.payments else 0
        out = self.invoice_amount - total_paid if self.invoice_amount else 0
        od = 0
        if self.due_date:
            from datetime import date as d
            try:
                due = datetime.strptime(self.due_date, "%Y-%m-%d").date()
                if due < d.today() and out > 0:
                    od = (d.today() - due).days
            except Exception:
                pass
        return {
            "id": self.id,
            "client_id": self.client_id,
            "client_name": self.client.client_name if self.client else None,
            "brand_name": self.client.brand_name if self.client else None,
            "business_manager_id": self.business_manager_id,
            "business_manager_name": self.bm.full_name or self.bm.email if self.bm else None,
            "billing_type": self.billing_type,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date,
            "invoice_period": self.invoice_period,
            "invoice_amount": self.invoice_amount,
            "due_date": self.due_date,
            "amount_received": round(total_paid, 2),
            "outstanding_amount": round(out, 2),
            "invoice_status": self.invoice_status,
            "payment_status": self.payment_status,
            "overdue_days": od,
            "remarks": self.remarks,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "base_amount": self.base_amount,
            "gst_amount": self.gst_amount,
            "cgst_amount": self.cgst_amount,
            "sgst_amount": self.sgst_amount,
            "igst_amount": self.igst_amount,
            "description": self.description,
            "jobcard_number": self.jobcard_number,
            "po_reference": self.po_reference,
            "document_file_path": self.document_file_path,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RevPayment(Base):
    __tablename__ = "rev_payments"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("rev_invoices.id"), nullable=False)
    client_id = Column(Integer, ForeignKey("rev_clients.id"), nullable=False)
    payment_date = Column(String, nullable=False)
    amount = Column(Float, default=0.0)
    payment_mode = Column(String, default=PaymentMode.BANK_TRANSFER.value)
    reference_number = Column(String, nullable=True)
    payment_proof_url = Column(String, nullable=True)
    remarks = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    invoice = relationship("RevInvoice", back_populates="payments")
    client = relationship("RevClient")

    def to_dict(self):
        return {
            "id": self.id,
            "invoice_id": self.invoice_id,
            "client_id": self.client_id,
            "client_name": self.client.client_name if self.client else None,
            "invoice_number": self.invoice.invoice_number if self.invoice else None,
            "payment_date": self.payment_date,
            "amount": self.amount,
            "payment_mode": self.payment_mode,
            "reference_number": self.reference_number,
            "payment_proof_url": self.payment_proof_url,
            "remarks": self.remarks,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RevDocument(Base):
    __tablename__ = "rev_documents"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("rev_clients.id"), nullable=False)
    invoice_id = Column(Integer, ForeignKey("rev_invoices.id"), nullable=True)
    document_type = Column(String, default=DocType.OTHER.value)
    document_name = Column(String, nullable=False)
    file_url = Column(String, nullable=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("RevClient")
    invoice = relationship("RevInvoice", back_populates="documents")
    uploader = relationship("User", foreign_keys=[uploaded_by])

    def to_dict(self):
        return {
            "id": self.id,
            "client_id": self.client_id,
            "client_name": self.client.client_name if self.client else None,
            "invoice_id": self.invoice_id,
            "document_type": self.document_type,
            "document_name": self.document_name,
            "file_url": self.file_url,
            "uploaded_by": self.uploaded_by,
            "uploaded_by_name": self.uploader.full_name or self.uploader.email if self.uploader else None,
            "remarks": self.remarks,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RevReminder(Base):
    __tablename__ = "rev_reminders"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("rev_clients.id"), nullable=False)
    invoice_id = Column(Integer, ForeignKey("rev_invoices.id"), nullable=True)
    business_manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reminder_type = Column(String, nullable=False)
    priority = Column(String, default=ReminderPriority.MEDIUM.value)
    reminder_status = Column(String, default=ReminderStatus.OPEN.value)
    due_amount = Column(Float, default=0.0)
    due_date = Column(String, nullable=True)
    next_followup_date = Column(String, nullable=True)
    last_followup_date = Column(String, nullable=True)
    snooze_until = Column(String, nullable=True)
    auto_generated = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("RevClient")
    invoice = relationship("RevInvoice", back_populates="reminders")
    business_manager = relationship("User", foreign_keys=[business_manager_id])

    def to_dict(self):
        return {
            "id": self.id,
            "client_id": self.client_id,
            "client_name": self.client.client_name if self.client else None,
            "invoice_id": self.invoice_id,
            "invoice_number": self.invoice.invoice_number if self.invoice else None,
            "business_manager_id": self.business_manager_id,
            "business_manager_name": self.business_manager.full_name or self.business_manager.email if self.business_manager else None,
            "reminder_type": self.reminder_type,
            "priority": self.priority,
            "reminder_status": self.reminder_status,
            "due_amount": self.due_amount,
            "due_date": self.due_date,
            "next_followup_date": self.next_followup_date,
            "last_followup_date": self.last_followup_date,
            "snooze_until": self.snooze_until,
            "auto_generated": self.auto_generated,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class FollowupNote(Base):
    __tablename__ = "followup_notes"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("rev_clients.id"), nullable=False)
    invoice_id = Column(Integer, ForeignKey("rev_invoices.id"), nullable=True)
    business_manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    note = Column(Text, nullable=False)
    next_followup_date = Column(String, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("RevClient")
    invoice = relationship("RevInvoice")
    business_manager = relationship("User", foreign_keys=[business_manager_id])
    creator = relationship("User", foreign_keys=[created_by])

    def to_dict(self):
        return {
            "id": self.id,
            "client_id": self.client_id,
            "client_name": self.client.client_name if self.client else None,
            "invoice_id": self.invoice_id,
            "invoice_number": self.invoice.invoice_number if self.invoice else None,
            "business_manager_id": self.business_manager_id,
            "business_manager_name": self.business_manager.full_name or self.business_manager.email if self.business_manager else None,
            "note": self.note,
            "next_followup_date": self.next_followup_date,
            "created_by": self.created_by,
            "created_by_name": self.creator.full_name or self.creator.email if self.creator else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditLog(Base):
    __tablename__ = "rev_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_name": self.user.full_name or self.user.email if self.user else None,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RevSetting(Base):
    __tablename__ = "rev_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, nullable=False, unique=True)
    value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "key": self.key,
            "value": self.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }