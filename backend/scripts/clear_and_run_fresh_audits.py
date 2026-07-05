"""Clear old pending actions for DSU/DSI and run fresh smart audits with rate-limit retries."""
import time
import logging
from backend.db.database import SessionLocal
from backend.db.models import Account, PendingAction
from backend.services.scheduler import run_manual_smart_audit


logger = logging.getLogger("AdOptima")
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

def clear_old_actions(account_id: int) -> int:
    """Delete pending actions with no confidence_score for this account."""
    db = SessionLocal()
    try:
        q = db.query(PendingAction).filter(
            PendingAction.account_id == account_id,
            PendingAction.status == "pending",
            PendingAction.confidence_score.is_(None),
        )
        count = q.count()
        q.delete(synchronize_session=False)
        db.commit()
        return count
    finally:
        db.close()

def run_audit_with_retry(account_id: int, account_name: str) -> dict:
    """Run smart audit with 3-second retry on Gemini rate limits."""
    max_retries = 5
    for attempt in range(max_retries):
        logger.info(f"Running smart audit for {account_name} (attempt {attempt + 1}/{max_retries})")
        result = run_manual_smart_audit(account_id)
        if "error" not in result:
            return result
        err = result.get("error", "").lower()
        if "429" in err or "503" in err or "quota" in err or "unavailable" in err:
            logger.warning(f"Rate limit / unavailable for {account_name}: {err}")
            logger.info(f"Waiting 3 seconds before retry...")
            time.sleep(3)
            continue
        # Other error, no retry
        return result
    return result

# Clear old actions
for name, aid in [("DSU", 1), ("DSI", 2)]:
    logger.info(f"Clearing old pending actions for {name}...")
    cleared = clear_old_actions(aid)
    logger.info(f"Cleared {cleared} old actions for {name}")

# Run DSU smart audit first
logger.info("=" * 60)
logger.info("RUNNING DSU SMART AUDIT")
logger.info("=" * 60)
dsu_result = run_audit_with_retry(1, "DSU")
logger.info(f"DSU result: {dsu_result}")

# Wait between accounts
logger.info("Waiting 10 seconds before DSI audit...")
time.sleep(10)

# Run DSI smart audit
logger.info("=" * 60)
logger.info("RUNNING DSI SMART AUDIT")
logger.info("=" * 60)
dsi_result = run_audit_with_retry(2, "DSI")
logger.info(f"DSI result: {dsi_result}")

print("\nDone.")