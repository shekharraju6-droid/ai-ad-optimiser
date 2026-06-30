"""
One-time fix: recreate RevClient records for every central Account that does not have one.

This restores the RevenueOps client list after the demo cleanup deleted all RevClients.
"""
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.db.database import get_db
from backend.db.models import Account
from backend.db.revenueops_models import RevClient, RevClientStatus


def main():
    db = next(get_db())
    try:
        accounts = db.query(Account).all()
        created = 0
        linked = 0
        for a in accounts:
            if a.rev_client_id:
                # Already linked; verify it exists
                existing = db.query(RevClient).filter(RevClient.id == a.rev_client_id).first()
                if existing:
                    continue
            # Create a new RevClient from account data
            client = RevClient(
                account_id=a.id,
                client_name=a.name,
                brand_name=a.brand_name,
                contact_person=a.contact_person,
                contact_email=a.contact_email,
                contact_phone=a.contact_phone,
                business_manager_id=a.business_manager_id,
                client_status=RevClientStatus.ACTIVE.value,
                invoice_day=1,
                default_due_days=30,
            )
            db.add(client)
            db.flush()
            a.rev_client_id = client.id
            created += 1
        db.commit()
        print(f"Processed {len(accounts)} accounts.")
        print(f"Created {created} new RevClients and linked them.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
