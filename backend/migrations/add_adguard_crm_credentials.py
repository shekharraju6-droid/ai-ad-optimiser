"""
Safe additive migration: adguard_accounts.crm_credentials (encrypted JSON).

Stores the subscriber's CRM connection credentials (encrypted with the same
Fernet scheme as google_credentials):
  - leadsquared: {"access_key","secret_key","host"(optional)}
  - zoho:        {"client_id","client_secret","refresh_token","api_domain"}
  - salesforce:  {"instance_url","access_token"} (or refresh flow later)
  - hubspot:     {"access_token"} (private app token)
  - webhook:     {"url","secret"(optional)}
"""
import logging
from sqlalchemy import text, inspect
from backend.db.database import engine, get_active_db

logger = logging.getLogger("AdOptima")


def run_migration():
    active = get_active_db()
    logger.info(f"Running adguard crm_credentials migration on {active}")
    try:
        inspector = inspect(engine)
        cols = {c["name"] for c in inspector.get_columns("adguard_accounts")}
    except Exception as e:
        logger.warning(f"Migration skipped (inspect failed): {e}")
        return
    if "crm_credentials" in cols:
        logger.info("adguard_accounts.crm_credentials already present")
        return
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE adguard_accounts ADD COLUMN crm_credentials TEXT NULL"))
        logger.info("Added column adguard_accounts.crm_credentials")
    except Exception as e:
        logger.warning(f"Add crm_credentials failed: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()