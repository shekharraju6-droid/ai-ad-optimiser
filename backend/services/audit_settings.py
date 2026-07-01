"""
Configurable thresholds for smart keyword and search term audits.
Values are stored in app_settings table.
"""
from typing import Dict, Any
from sqlalchemy.orm import Session
from backend.db.database import SessionLocal
from backend.db.models import AppSetting

DEFAULTS = {
    "smart_audit_keyword_min_spend_inr": 500,
    "smart_audit_search_term_min_clicks": 2,
    "smart_audit_search_term_min_spend_inr": 100,
    "smart_audit_lookback_days": 30,
    "smart_audit_daily_time_ist": "08:00",
    "smart_audit_rejection_suppression_days": 30,
}


def _as_int(val, default: int) -> int:
    try:
        return int(val)
    except Exception:
        return default


def get_audit_settings(db: Session = None) -> Dict[str, Any]:
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    try:
        settings = dict(DEFAULTS)
        rows = db.query(AppSetting).filter(AppSetting.key.startswith("smart_audit_")).all()
        for row in rows:
            key = row.key
            if key not in DEFAULTS:
                continue
            default_val = DEFAULTS[key]
            raw = row.value
            if isinstance(default_val, int):
                settings[key] = _as_int(raw, default_val)
            else:
                settings[key] = raw if raw is not None else default_val
        return settings
    finally:
        if close_session:
            db.close()


def set_audit_setting(key: str, value: Any, db: Session = None) -> Dict[str, Any]:
    if key not in DEFAULTS:
        raise ValueError(f"Unknown audit setting: {key}")
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    try:
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value = str(value)
        else:
            row = AppSetting(key=key, value=str(value))
            db.add(row)
        db.commit()
        db.refresh(row)
        return row.to_dict()
    finally:
        if close_session:
            db.close()


def get_int_setting(key: str, db: Session = None) -> int:
    settings = get_audit_settings(db)
    return _as_int(settings.get(key), DEFAULTS[key])
