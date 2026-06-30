"""
Migration: add account_id column to rev_clients and populate it.
"""
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.db.database import engine
from sqlalchemy import text


def main():
    with engine.begin() as conn:
        # Add column if missing
        conn.execute(text("""
            ALTER TABLE rev_clients
            ADD COLUMN IF NOT EXISTS account_id INTEGER;
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_rev_clients_account_id
            ON rev_clients (account_id);
        """))
        # Populate account_id from accounts.rev_client_id
        conn.execute(text("""
            UPDATE rev_clients
            SET account_id = accounts.id
            FROM accounts
            WHERE accounts.rev_client_id = rev_clients.id
              AND rev_clients.account_id IS NULL;
        """))
    print("Migration complete.")


if __name__ == "__main__":
    main()
