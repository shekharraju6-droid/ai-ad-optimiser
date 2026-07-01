"""
Safe additive migration for AI Invoice Upload (RevenueOps).
Adds new columns to rev_invoices if they don't already exist.
Works on PostgreSQL and SQLite. Idempotent.
"""
import logging
from sqlalchemy import text, inspect
from backend.db.database import engine, get_active_db

logger = logging.getLogger("AdOptima")

COLUMNS = [
    ("base_amount", "FLOAT"),
    ("gst_amount", "FLOAT"),
    ("cgst_amount", "FLOAT"),
    ("sgst_amount", "FLOAT"),
    ("igst_amount", "FLOAT"),
    ("description", "TEXT"),
    ("jobcard_number", "VARCHAR"),
    ("po_reference", "VARCHAR"),
    ("document_file_path", "VARCHAR"),
    ("source", "VARCHAR DEFAULT 'manual'"),
]


def _existing_columns(table):
    inspector = inspect(engine)
    try:
        return {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return set()


def run_migration():
    return run_invoice_migration()


def run_invoice_migration():
    active = get_active_db()
    logger.info(f"Running rev_invoices column migration on {active}")
    try:
        existing = _existing_columns("rev_invoices")
    except Exception as e:
        logger.warning(f"rev_invoices migration skipped (inspect failed): {e}")
        return
    missing = [(n, d) for n, d in COLUMNS if n not in existing]
    if not missing:
        logger.info("All rev_invoices columns already present, migration skipped")
        return
    with engine.begin() as conn:
        for col_name, col_def in missing:
            if active.startswith("postgresql"):
                sql = f'ALTER TABLE rev_invoices ADD COLUMN IF NOT EXISTS {col_name} {col_def}'
            else:
                sql = f'ALTER TABLE rev_invoices ADD COLUMN {col_name} {col_def}'
            logger.info(f"Adding column rev_invoices.{col_name}")
            conn.execute(text(sql))
    logger.info("rev_invoices column migration complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()