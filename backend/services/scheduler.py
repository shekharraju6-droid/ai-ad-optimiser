"""
Background scheduler for running automatic audits.
Reads global and per-account audit intervals.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from backend.services.auditor import audit_account, audit_all_accounts
from backend.db.database import SessionLocal
from backend.db.models import Account
from backend.services.config import load_config

logger = logging.getLogger("AdOptima")
_scheduler = None


def start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler()
    # Recalculate schedules every minute
    _scheduler.add_job(_reschedule_all, 'interval', minutes=1, id='schedule_refresher', replace_existing=True)
    _scheduler.start()
    logger.info("Background scheduler started")


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        _scheduler = None
        logger.info("Background scheduler stopped")


def _reschedule_all():
    """Dynamic rescheduling based on global and per-account settings."""
    if not _scheduler:
        return

    global_interval = _global_audit_interval()

    db = SessionLocal()
    try:
        accounts = db.query(Account).filter(Account.is_active == True).all()
        for account in accounts:
            for platform in ["google", "meta"]:
                if (platform == "google" and not account.has_google) or (platform == "meta" and not account.has_meta):
                    continue
                job_id = f"audit_{account.id}_{platform}"
                interval = account.audit_interval_minutes if account.audit_interval_minutes else global_interval
                if interval is None or interval <= 0:
                    # disabled
                    try:
                        _scheduler.remove_job(job_id)
                    except Exception:
                        pass
                    continue
                try:
                    existing = _scheduler.get_job(job_id)
                    if existing and getattr(existing.trigger, 'interval', None) == interval:
                        continue
                except Exception:
                    pass
                try:
                    _scheduler.remove_job(job_id)
                except Exception:
                    pass
                _scheduler.add_job(
                    _run_account_audit,
                    'interval',
                    minutes=max(15, interval),
                    id=job_id,
                    replace_existing=True,
                    args=[account.id, platform],
                )
                logger.info(f"Scheduled audit for account {account.id} ({platform}) every {interval} minutes")

        # Global fallback audit job
        global_job_id = "global_audit"
        if global_interval and global_interval > 0:
            try:
                existing = _scheduler.get_job(global_job_id)
                if not existing or getattr(existing.trigger, 'interval', None) != global_interval:
                    _scheduler.remove_job(global_job_id)
                    _scheduler.add_job(_scheduled_audit_tick, 'interval', minutes=max(15, global_interval), id=global_job_id, replace_existing=True)
            except Exception:
                _scheduler.add_job(_scheduled_audit_tick, 'interval', minutes=max(15, global_interval), id=global_job_id, replace_existing=True)
        else:
            try:
                _scheduler.remove_job(global_job_id)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Rescheduling failed: {e}")
    finally:
        db.close()


def _global_audit_interval() -> int:
    cfg = load_config()
    val = cfg.get("global_audit_interval_minutes")
    try:
        return int(val) if val else 60
    except Exception:
        return 60


def _scheduled_audit_tick():
    logger.info("Running scheduled global audit")
    try:
        result = audit_all_accounts()
        logger.info(f"Scheduled audit complete: {result.get('total_actions_generated', 0)} actions generated")
    except Exception as e:
        logger.error(f"Scheduled audit failed: {e}")


def _run_account_audit(account_id: int, platform: str):
    logger.info(f"Running scheduled audit for account {account_id} ({platform})")
    try:
        audit_account(account_id, platform=platform)
    except Exception as e:
        logger.error(f"Account audit failed: {e}")


def schedule_account_audit(account_id: int, interval_minutes: int):
    """Manual helper to schedule a per-account audit immediately."""
    if not _scheduler:
        start_scheduler()
    _reschedule_all()


def remove_account_schedule(account_id: int):
    if _scheduler:
        for platform in ["google", "meta"]:
            job_id = f"audit_{account_id}_{platform}"
            try:
                _scheduler.remove_job(job_id)
            except Exception:
                pass
