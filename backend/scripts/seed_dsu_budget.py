"""
Seed DSU budget entries from the screenshot / raw data.
Run: python -m backend.scripts.seed_dsu_budget
"""

from backend.db.database import Base, engine, SessionLocal
from backend.db import models

BUDGET_ENTRIES = [
    # (date, amount, invoice, campus)
    ("2025-11-01", 380000, "-", "Campus 4"),
    ("2025-12-01", 380000, "-", "Campus 3"),
    ("2026-01-01", 380000, "-", "Campus 3"),
    ("2026-02-01", 380000, "-", "Campus 4"),
    ("2026-03-01", 220000, "-", "Campus 4"),
    ("2026-03-01", 380000, "-", "Campus 4"),
    ("2026-04-01", 480000, "-", "Campus 4"),
    ("2026-05-01", 380000, "-", "Campus 4"),
    ("2026-05-01", 480000, "-", "Campus 4"),
    ("2026-05-01", 400000, "-", "Campus 3"),
    ("2026-05-01", 380000, "-", "Campus 3"),
    ("2026-05-01", 400000, "-", "Campus 3"),
]


def seed():
    Base.metadata.create_all(bind=engine, tables=[models.DsuBudgetEntry.__table__])
    db = SessionLocal()
    try:
        # Clear existing entries to avoid duplicates
        db.query(models.DsuBudgetEntry).delete()
        db.flush()

        for date_str, amount, invoice, campus in BUDGET_ENTRIES:
            db.add(models.DsuBudgetEntry(
                entry_date=date_str,
                amount=amount,
                invoice=invoice,
                campus=campus,
            ))

        db.commit()

        entries = db.query(models.DsuBudgetEntry).all()
        total = sum(e.amount for e in entries)
        print(f"Seeded {len(entries)} DSU budget entries.")
        print(f"Total amount received: Rs. {total:,.2f}")
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
