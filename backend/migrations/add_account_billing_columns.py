"""
Safe additive migration for Phase 1 Single Client Master.
Adds new columns to the accounts table if they don't already exist.
Works on PostgreSQL and SQLite.

Run manually after deployment:
    python -m backend.migrations.add_account_billing_columns

Or call run_migration() from app startup (idempotent).
"""
import os
import logging
from sqlalchemy import text, inspect
from backend.db.database import engine, get_active_db

logger = logging.getLogger("AdOptima")

COLUMNS = [
    ("client_status", "VARCHAR DEFAULT 'Active'"),
    ("invoice_day", "INTEGER"),
    ("payment_due_days", "INTEGER DEFAULT 45"),
    ("billing_amount", "FLOAT"),
    ("gst_number", "VARCHAR"),
    ("address", "TEXT"),
    ("state", "VARCHAR"),
    ("state_code", "VARCHAR"),
    ("adpulse_refresh_interval", "INTEGER DEFAULT 5"),
    ("adpulse_audit_interval", "INTEGER DEFAULT 60"),
]


def _existing_columns(table):
    """Return set of existing column names. Uses a separate connection so we
    don't deadlock inside an open transaction on PostgreSQL."""
    inspector = inspect(engine)
    try:
        return {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return set()


def run_migration():
    active = get_active_db()
    logger.info(f"Running account billing column migration on {active}")
    # Inspect existing columns BEFORE opening a transaction to avoid locks.
    try:
        existing = _existing_columns("accounts")
    except Exception as e:
        logger.warning(f"Account billing migration skipped (inspect failed): {e}")
        return
    missing = [(n, d) for n, d in COLUMNS if n not in existing]
    if not missing:
        logger.info("All account billing columns already present, migration skipped")
        return
    with engine.begin() as conn:
        for col_name, col_def in missing:
            if active.startswith("postgresql"):
                sql = f'ALTER TABLE accounts ADD COLUMN IF NOT EXISTS {col_name} {col_def}'
            else:
                sql = f'ALTER TABLE accounts ADD COLUMN {col_name} {col_def}'
            logger.info(f"Adding column accounts.{col_name}")
            conn.execute(text(sql))
    logger.info("Account billing column migration complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
