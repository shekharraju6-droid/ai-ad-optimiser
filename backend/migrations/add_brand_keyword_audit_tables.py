"""
Safe additive migration for Smart Keyword & Search Term Auditor (Phase 2).
Adds:
  - accounts.brand_keywords (TEXT nullable)
  - campaign_type_tags table
  - audit_runs table
  - suppressed_search_terms table

Works on PostgreSQL and SQLite. Idempotent.

Run manually after deployment:
    python -m backend.migrations.add_brand_keyword_audit_tables
"""
import os
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


def _table_exists(table):
    inspector = inspect(engine)
    try:
        return table in inspector.get_table_names()
    except Exception:
        return False


def run_migration():
    active = get_active_db()
    logger.info(f"Running brand keyword audit migration on {active}")

    # Add brand_keywords column to accounts if missing
    try:
        existing_accounts_cols = _existing_columns("accounts")
    except Exception as e:
        logger.warning(f"Migration skipped (inspect accounts failed): {e}")
        return

    if "brand_keywords" not in existing_accounts_cols:
        with engine.begin() as conn:
            if active.startswith("postgresql"):
                sql = "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS brand_keywords TEXT"
            else:
                sql = "ALTER TABLE accounts ADD COLUMN brand_keywords TEXT"
            logger.info("Adding column accounts.brand_keywords")
            conn.execute(text(sql))
    else:
        logger.info("accounts.brand_keywords already present")

    # Create campaign_type_tags table
    if not _table_exists("campaign_type_tags"):
        with engine.begin() as conn:
            logger.info("Creating table campaign_type_tags")
            if active.startswith("postgresql"):
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS campaign_type_tags (
                        id SERIAL PRIMARY KEY,
                        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                        campaign_id VARCHAR NOT NULL,
                        campaign_name VARCHAR,
                        campaign_type VARCHAR DEFAULT 'auto',
                        updated_by VARCHAR,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            else:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS campaign_type_tags (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                        campaign_id VARCHAR NOT NULL,
                        campaign_name VARCHAR,
                        campaign_type VARCHAR DEFAULT 'auto',
                        updated_by VARCHAR,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_type_tags_account_campaign ON campaign_type_tags(account_id, campaign_id)"))
    else:
        logger.info("campaign_type_tags table already exists")

    # Create audit_runs table
    if not _table_exists("audit_runs"):
        with engine.begin() as conn:
            logger.info("Creating table audit_runs")
            if active.startswith("postgresql"):
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS audit_runs (
                        id SERIAL PRIMARY KEY,
                        run_date DATE NOT NULL,
                        run_type VARCHAR NOT NULL,
                        start_time TIMESTAMP NOT NULL,
                        end_time TIMESTAMP,
                        accounts_audited INTEGER DEFAULT 0,
                        total_keyword_flags INTEGER DEFAULT 0,
                        total_search_term_flags INTEGER DEFAULT 0,
                        status VARCHAR DEFAULT 'pending',
                        error_log TEXT
                    )
                """))
            else:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS audit_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_date DATE NOT NULL,
                        run_type VARCHAR NOT NULL,
                        start_time TIMESTAMP NOT NULL,
                        end_time TIMESTAMP,
                        accounts_audited INTEGER DEFAULT 0,
                        total_keyword_flags INTEGER DEFAULT 0,
                        total_search_term_flags INTEGER DEFAULT 0,
                        status VARCHAR DEFAULT 'pending',
                        error_log TEXT
                    )
                """))
    else:
        logger.info("audit_runs table already exists")

    # Create suppressed_search_terms table
    if not _table_exists("suppressed_search_terms"):
        with engine.begin() as conn:
            logger.info("Creating table suppressed_search_terms")
            if active.startswith("postgresql"):
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS suppressed_search_terms (
                        id SERIAL PRIMARY KEY,
                        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                        campaign_id VARCHAR NOT NULL,
                        search_term VARCHAR NOT NULL,
                        suppressed_until DATE NOT NULL,
                        rejected_by VARCHAR,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            else:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS suppressed_search_terms (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                        campaign_id VARCHAR NOT NULL,
                        search_term VARCHAR NOT NULL,
                        suppressed_until DATE NOT NULL,
                        rejected_by VARCHAR,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_suppressed_search_terms_account_campaign_term ON suppressed_search_terms(account_id, campaign_id, search_term)"))
    else:
        logger.info("suppressed_search_terms table already exists")

    logger.info("Brand keyword audit migration complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
