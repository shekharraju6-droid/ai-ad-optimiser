"""
Safe additive migration for Smarter AI Auditor with Campaign Knowledge.

Adds:
  - accounts.business_context (TEXT nullable)
  - accounts.negative_rules (TEXT nullable)
  - pending_actions.confidence (VARCHAR nullable)  -- HIGH / MEDIUM / LOW
  - pending_actions.confidence_score (INTEGER nullable)  -- 0 to 100
  - campaign_landing_pages table (unique on account_id + campaign_id)

Works on PostgreSQL and SQLite. Idempotent.

Run manually after deployment:
    python -m backend.migrations.add_campaign_knowledge_schema
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


def _table_exists(table):
    inspector = inspect(engine)
    try:
        return table in inspector.get_table_names()
    except Exception:
        return False


def _add_text_column(table: str, column: str):
    active = get_active_db()
    cols = _existing_columns(table)
    if column in cols:
        logger.info(f"{table}.{column} already present")
        return
    with engine.begin() as conn:
        if active.startswith("postgresql"):
            sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} TEXT"
        else:
            sql = f"ALTER TABLE {table} ADD COLUMN {column} TEXT"
        logger.info(f"Adding column {table}.{column}")
        conn.execute(text(sql))


def _add_int_column(table: str, column: str):
    active = get_active_db()
    cols = _existing_columns(table)
    if column in cols:
        logger.info(f"{table}.{column} already present")
        return
    with engine.begin() as conn:
        if active.startswith("postgresql"):
            sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} INTEGER"
        else:
            sql = f"ALTER TABLE {table} ADD COLUMN {column} INTEGER"
        logger.info(f"Adding column {table}.{column}")
        conn.execute(text(sql))


def _add_varchar_column(table: str, column: str):
    active = get_active_db()
    cols = _existing_columns(table)
    if column in cols:
        logger.info(f"{table}.{column} already present")
        return
    with engine.begin() as conn:
        if active.startswith("postgresql"):
            sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} VARCHAR"
        else:
            sql = f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR"
        logger.info(f"Adding column {table}.{column}")
        conn.execute(text(sql))


def _create_campaign_landing_pages():
    active = get_active_db()
    if _table_exists("campaign_landing_pages"):
        logger.info("campaign_landing_pages table already exists")
        return
    with engine.begin() as conn:
        logger.info("Creating table campaign_landing_pages")
        if active.startswith("postgresql"):
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS campaign_landing_pages (
                    id SERIAL PRIMARY KEY,
                    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    campaign_id VARCHAR NOT NULL,
                    campaign_name VARCHAR,
                    landing_page_url VARCHAR,
                    landing_page_content TEXT,
                    last_crawled_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS campaign_landing_pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    campaign_id VARCHAR NOT NULL,
                    campaign_name VARCHAR,
                    landing_page_url VARCHAR,
                    landing_page_content TEXT,
                    last_crawled_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_clp_account_campaign "
            "ON campaign_landing_pages(account_id, campaign_id)"
        ))


def run_migration():
    active = get_active_db()
    logger.info(f"Running campaign knowledge schema migration on {active}")

    # Part 5: Account business context
    _add_text_column("accounts", "business_context")
    _add_text_column("accounts", "negative_rules")

    # Part 6: Pending action confidence
    _add_varchar_column("pending_actions", "confidence")
    _add_int_column("pending_actions", "confidence_score")

    # Part 3: Campaign landing pages table
    _create_campaign_landing_pages()

    logger.info("Campaign knowledge schema migration complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()