"""
Notification dispatcher for AdOptima.
Dispatches via real email/SMTP or Twilio WhatsApp when credentials are present;
falls back to logging a queued record when credentials are missing.
"""
import logging
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from backend.db.database import SessionLocal
from backend.db.models import NotificationSetting
from backend.services.notification_dispatch import dispatch_channel

logger = logging.getLogger("AdOptima")


def get_enabled_channels(db: Session = None) -> List[NotificationSetting]:
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    try:
        return db.query(NotificationSetting).filter(NotificationSetting.enabled == True).all()
    finally:
        if close_session:
            db.close()


def dispatch(event_type: str, subject: str, body: str, db: Session = None) -> List[Dict[str, Any]]:
    """
    Send a notification to all enabled channels that subscribe to event_type.
    event_type: 'audit_complete', 'action_reviewed', 'sync_failure'
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    try:
        event_attr = {
            "audit_complete": "notify_on_audit_complete",
            "action_reviewed": "notify_on_action_reviewed",
            "sync_failure": "notify_on_sync_failure",
        }.get(event_type)

        settings = db.query(NotificationSetting).filter(
            NotificationSetting.enabled == True
        ).all()

        results = []
        for setting in settings:
            if event_attr and not getattr(setting, event_attr, True):
                continue

            result = dispatch_channel(setting, event_type, subject, body, db)
            results.append(result)
        return results
    finally:
        if close_session:
            db.close()
