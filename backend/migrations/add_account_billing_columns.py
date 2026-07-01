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


def _column_exists(conn, table, column):
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns(table)]
    return column in cols


def run_migration():
    active = get_active_db()
    logger.info(f"Running account billing column migration on {active}")
    with engine.begin() as conn:
        for col_name, col_def in COLUMNS:
            if _column_exists(conn, "accounts", col_name):
                logger.info(f"Column accounts.{col_name} already exists, skipping")
                continue
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
