"""
One-time migration to normalize user roles.
- 'BM (User)' is no longer a valid role value; rename to 'BM' stored as 'user'.
- No role values change for admin/superadmin.

Run manually after deployment:
    python -m backend.migrations.normalize_user_roles
"""
import os
import logging
from sqlalchemy import text
from backend.db.database import engine, get_active_db

logger = logging.getLogger("AdOptima")


def run_migration():
    active = get_active_db()
    logger.info(f"Running user role normalization migration on {active}")

    try:
        with engine.begin() as conn:
            # The DB stores 'BM' as 'user' internally; old text label 'BM (User)' should not exist,
            # but if any legacy rows used the literal string we normalize them.
            if active.startswith("postgresql"):
                conn.execute(text("UPDATE users SET role = 'user' WHERE role = 'BM (User)'"))
                conn.execute(text("UPDATE users SET role = 'user' WHERE role = 'BM'"))
            else:
                conn.execute(text("UPDATE users SET role = 'user' WHERE role = 'BM (User)'"))
                conn.execute(text("UPDATE users SET role = 'user' WHERE role = 'BM'"))
        logger.info("User role normalization complete")
    except Exception as e:
        logger.warning(f"User role normalization migration skipped/failed: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
