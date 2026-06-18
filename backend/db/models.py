"""
Database models for AdOptima AI.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, ForeignKey, Enum, JSON
from sqlalchemy.orm import relationship
from backend.db.database import Base
import enum


class AccountType(str, enum.Enum):
    GOOGLE = "google"
    META = "meta"
    BOTH = "both"


class AccountStatus(str, enum.Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    DISCONNECTED = "disconnected"
    SYNCING = "syncing"


class AccountGroup(Base):
    __tablename__ = "account_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    accounts = relationship("Account", back_populates="group", lazy="dynamic")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("account_groups.id"), nullable=True)

    name = Column(String, nullable=False)  # Client name, e.g. DSU
    account_type = Column(Enum(AccountType), nullable=False)  # legacy single-platform type
    external_id = Column(String, nullable=False)  # legacy single-platform external id
    currency = Column(String, default="INR")
    timezone = Column(String, default="Asia/Kolkata")

    # Per-platform flags: which platforms are enabled for this client
    has_google = Column(Boolean, default=True)
    has_meta = Column(Boolean, default=False)

    # Per-platform credentials (encrypted at rest)
    google_credentials = Column(Text, nullable=True)
    meta_credentials = Column(Text, nullable=True)

    # Per-platform external IDs
    google_external_id = Column(String, nullable=True)
    meta_external_id = Column(String, nullable=True)

    # Per-platform live/mock flags
    google_is_live = Column(Boolean, default=False)
    meta_is_live = Column(Boolean, default=False)

    # Per-platform OAuth app credential overrides (for separate MCC accounts)
    google_client_id = Column(String, nullable=True)
    google_client_secret = Column(String, nullable=True)
    google_developer_token = Column(String, nullable=True)
    meta_app_id = Column(String, nullable=True)
    meta_app_secret = Column(String, nullable=True)
    redirect_base_url = Column(String, nullable=True)

    # Credentials (encrypted at rest via app-level encryption) - legacy fallback
    credentials = Column(Text, nullable=True)

    # Sync settings
    refresh_interval_minutes = Column(Integer, default=60)
    audit_interval_minutes = Column(Integer, default=60)  # auto audit frequency
    is_active = Column(Boolean, default=True)
    is_live = Column(Boolean, default=False)
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_error = Column(Text, nullable=True)

    # Cached dashboard metrics
    status = Column(Enum(AccountStatus), default=AccountStatus.DISCONNECTED)
    spend = Column(Float, default=0.0)
    conversions = Column(Float, default=0.0)
    clicks = Column(Float, default=0.0)
    impressions = Column(Float, default=0.0)
    ctr = Column(Float, default=0.0)
    cpa = Column(Float, default=0.0)
    budget = Column(Float, default=0.0)
    budget_used_pct = Column(Float, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    group = relationship("AccountGroup", back_populates="accounts")

    def to_dict(self):
        return {
            "id": self.id,
            "group_id": self.group_id,
            "group_name": self.group.name if self.group else None,
            "name": self.name,
            "account_type": self.account_type.value,
            "external_id": self.external_id,
            "currency": self.currency,
            "timezone": self.timezone,
            "has_google": self.has_google,
            "has_meta": self.has_meta,
            "google_external_id": self.google_external_id,
            "meta_external_id": self.meta_external_id,
            "google_is_live": self.google_is_live,
            "meta_is_live": self.meta_is_live,
            "google_credentials_masked": bool(self.google_credentials),
            "meta_credentials_masked": bool(self.meta_credentials),
            "google_client_id": self.google_client_id,
            "google_client_secret": self.google_client_secret,
            "google_developer_token": self.google_developer_token,
            "meta_app_id": self.meta_app_id,
            "meta_app_secret": self.meta_app_secret,
            "redirect_base_url": self.redirect_base_url,
            "refresh_interval_minutes": self.refresh_interval_minutes,
            "audit_interval_minutes": self.audit_interval_minutes,
            "is_active": self.is_active,
            "is_live": self.is_live,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "last_sync_error": self.last_sync_error,
            "status": self.status.value,
            "spend": self.spend,
            "conversions": self.conversions,
            "clicks": self.clicks,
            "impressions": self.impressions,
            "ctr": self.ctr,
            "cpa": self.cpa,
            "budget": self.budget,
            "budget_used_pct": self.budget_used_pct,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PendingAction(Base):
    __tablename__ = "pending_actions"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    action_type = Column(String, nullable=False)  # e.g. ADD_NEGATIVE_KEYWORD, PAUSE_CAMPAIGN, UPDATE_BUDGET
    platform = Column(String, nullable=False)  # google or meta
    campaign_id = Column(String, nullable=True)
    adset_id = Column(String, nullable=True)
    keyword = Column(String, nullable=True)
    match_type = Column(String, nullable=True)
    new_value = Column(JSON, nullable=True)  # flexible payload
    reason = Column(Text, nullable=True)
    estimated_savings = Column(Float, nullable=True)
    status = Column(String, default="pending")  # pending, approved, rejected, applied, failed
    requested_by = Column(String, nullable=True)
    reviewed_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    account = relationship("Account")

    def to_dict(self):
        return {
            "id": self.id,
            "account_id": self.account_id,
            "account_name": self.account.name if self.account else None,
            "action_type": self.action_type,
            "platform": self.platform,
            "campaign_id": self.campaign_id,
            "adset_id": self.adset_id,
            "keyword": self.keyword,
            "match_type": self.match_type,
            "new_value": self.new_value,
            "reason": self.reason,
            "estimated_savings": self.estimated_savings,
            "status": self.status,
            "requested_by": self.requested_by,
            "reviewed_by": self.reviewed_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
            "error_message": self.error_message,
        }


class NotificationSetting(Base):
    __tablename__ = "notification_settings"

    id = Column(Integer, primary_key=True, index=True)
    channel = Column(String, nullable=False, unique=True)  # email, whatsapp
    enabled = Column(Boolean, default=False)
    provider = Column(String, nullable=True)  # e.g. "twilio", "sendgrid", "smtp"
    config = Column(JSON, nullable=True)  # credentials / recipient mapping
    notify_on_audit_complete = Column(Boolean, default=True)
    notify_on_action_reviewed = Column(Boolean, default=True)
    notify_on_sync_failure = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "channel": self.channel,
            "enabled": self.enabled,
            "provider": self.provider,
            "config": self.config,
            "notify_on_audit_complete": self.notify_on_audit_complete,
            "notify_on_action_reviewed": self.notify_on_action_reviewed,
            "notify_on_sync_failure": self.notify_on_sync_failure,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True, index=True)
    channel = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    recipients = Column(JSON, nullable=True)
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    status = Column(String, default="queued")  # queued, sent, failed
    provider_response = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "channel": self.channel,
            "event_type": self.event_type,
            "recipients": self.recipients,
            "subject": self.subject,
            "body": self.body,
            "status": self.status,
            "provider_response": self.provider_response,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False, unique=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    role = Column(String, default="user")  # user, admin
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
