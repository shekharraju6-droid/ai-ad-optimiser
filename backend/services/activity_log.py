"""Central activity logging utility."""
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from backend.db.database import SessionLocal
from backend.db.models import ActivityLog

logger = logging.getLogger("AdOptima")


def log_activity(
    module: str,
    action: str,
    description: str,
    user_id: Optional[int] = None,
    user_name: Optional[str] = None,
    account_id: Optional[int] = None,
    account_name: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    db: Optional[Session] = None,
):
    """Create an activity_log record and commit.

    If db is not provided, opens a short-lived session. This is safe for
    logging from places that don't already have a session.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        entry = ActivityLog(
            timestamp=datetime.utcnow(),
            module=module,
            action=action,
            description=description,
            user_id=user_id,
            user_name=user_name,
            account_id=account_id,
            account_name=account_name,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details_json=json.dumps(details, default=str) if details else None,
        )
        db.add(entry)
        db.commit()
        return entry.to_dict()
    except Exception as e:
        logger.error(f"Failed to write activity log: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        if close_db:
            try:
                db.close()
            except Exception:
                pass
