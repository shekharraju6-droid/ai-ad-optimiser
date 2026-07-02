"""
Safe additive migration to add users.access_audit_review column.
Idempotent. Works on PostgreSQL and SQLite.

Run manually after deployment:
    python -m backend.migrations.add_audit_review_access
"""
import logging
from sqlalchemy import text, inspect
from backend.db.database import engine, get_active_db

logger = logging.getLogger("AdOptima")


def _existing_columns(table):
    inspector = inspect(engine)
    try:
        return {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return set()


def run_migration():
    active = get_active_db()
    logger.info(f"Running audit review access migration on {active}")

    try:
        existing_cols = _existing_columns("users")
    except Exception as e:
        logger.warning(f"Migration skipped (inspect users failed): {e}")
        return

    if "access_audit_review" not in existing_cols:
        with engine.begin() as conn:
            if active.startswith("postgresql"):
                sql = "ALTER TABLE users ADD COLUMN IF NOT EXISTS access_audit_review BOOLEAN DEFAULT FALSE"
            else:
                sql = "ALTER TABLE users ADD COLUMN access_audit_review BOOLEAN DEFAULT FALSE"
            logger.info("Adding column users.access_audit_review")
            conn.execute(text(sql))
    else:
        logger.info("users.access_audit_review already present")

    logger.info("Audit review access migration complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()