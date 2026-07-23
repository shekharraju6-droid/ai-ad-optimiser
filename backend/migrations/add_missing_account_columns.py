"""
Safe additive migration to add missing columns to the accounts table.
Works on PostgreSQL and SQLite.

Run manually after deployment:
    python -m backend.migrations.add_missing_account_columns

Or call run_migration() from app startup (idempotent).
"""
import logging
from sqlalchemy import text, inspect
from backend.db.database import engine, get_active_db

logger = logging.getLogger("AdOptima")

COLUMNS = [
    ("google_login_customer_id", "VARCHAR"),
    ("rev_client_id", "INTEGER"),
    ("business_manager_id", "INTEGER"),
    ("contact_phone", "VARCHAR"),
    ("brand_name", "VARCHAR"),
    ("contact_email", "VARCHAR"),
    ("lsq_sync_interval_minutes", "INTEGER DEFAULT 10"),
    ("contact_person", "VARCHAR"),
]


def _existing_columns(table):
    """Return set of existing column names."""
    inspector = inspect(engine)
    try:
        return {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return set()


def run_migration():
    active = get_active_db()
    logger.info(f"Running missing account columns migration on {active}")
    try:
        existing = _existing_columns("accounts")
    except Exception as e:
        logger.warning(f"Missing account columns migration skipped (inspect failed): {e}")
        return
    missing = [(n, d) for n, d in COLUMNS if n not in existing]
    if not missing:
        logger.info("All missing account columns already present, migration skipped")
        return
    with engine.begin() as conn:
        for col_name, col_def in missing:
            if active.startswith("postgresql"):
                sql = f'ALTER TABLE accounts ADD COLUMN IF NOT EXISTS {col_name} {col_def}'
            else:
                sql = f'ALTER TABLE accounts ADD COLUMN {col_name} {col_def}'
            logger.info(f"Adding column accounts.{col_name}")
            conn.execute(text(sql))
    logger.info("Missing account columns migration complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
