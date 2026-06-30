"""
One-time cleanup: remove all RevenueOps transactional demo data.

Keeps central Account records intact but clears:
- RevInvoices
- RevPayments
- RevDocuments
- RevReminders
- FollowupNotes
- AuditLogs
- RevClients
- Account.rev_client_id links

After running, the RevenueOps dashboard will show zeros in all cards.
"""
import os
import sys

# Load env from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.db.database import get_db, engine
from backend.db.models import Account
from backend.db.revenueops_models import (
    RevClient,
    RevInvoice,
    RevPayment,
    RevDocument,
    RevReminder,
    FollowupNote,
    AuditLog,
    ClientBillingModel,
)
from sqlalchemy.orm import sessionmaker


def main():
    db = next(get_db())
    try:
        print("Counts before cleanup:")
        print(f"  Accounts: {db.query(Account).count()}")
        print(f"  RevClients: {db.query(RevClient).count()}")
        print(f"  RevInvoices: {db.query(RevInvoice).count()}")
        print(f"  RevPayments: {db.query(RevPayment).count()}")
        print(f"  RevDocuments: {db.query(RevDocument).count()}")
        print(f"  RevReminders: {db.query(RevReminder).count()}")
        print(f"  FollowupNotes: {db.query(FollowupNote).count()}")
        print(f"  AuditLogs: {db.query(AuditLog).count()}")
        print(f"  ClientBillingModels: {db.query(ClientBillingModel).count()}")

        confirm = input("\nThis will DELETE all RevenueOps data. Type 'yes' to proceed: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return

        # Delete transactional data first (respect FKs)
        db.query(RevPayment).delete(synchronize_session=False)
        db.query(RevDocument).delete(synchronize_session=False)
        db.query(RevReminder).delete(synchronize_session=False)
        db.query(FollowupNote).delete(synchronize_session=False)
        db.query(AuditLog).delete(synchronize_session=False)
        db.query(RevInvoice).delete(synchronize_session=False)
        db.query(ClientBillingModel).delete(synchronize_session=False)
        db.query(RevClient).delete(synchronize_session=False)

        # Unlink accounts from deleted rev clients
        db.query(Account).update({Account.rev_client_id: None}, synchronize_session=False)

        db.commit()

        print("\nCounts after cleanup:")
        print(f"  Accounts: {db.query(Account).count()}")
        print(f"  RevClients: {db.query(RevClient).count()}")
        print(f"  RevInvoices: {db.query(RevInvoice).count()}")
        print(f"  RevPayments: {db.query(RevPayment).count()}")
        print(f"  RevDocuments: {db.query(RevDocument).count()}")
        print(f"  RevReminders: {db.query(RevReminder).count()}")
        print(f"  FollowupNotes: {db.query(FollowupNote).count()}")
        print(f"  AuditLogs: {db.query(AuditLog).count()}")
        print(f"  ClientBillingModels: {db.query(ClientBillingModel).count()}")
        print("\nCleanup complete.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
