"""Check confidence stored in new_value JSON for SMART negative keyword actions."""
from backend.db.database import SessionLocal
from backend.db.models import PendingAction

db = SessionLocal()
actions = db.query(PendingAction).filter(
    PendingAction.account_id == 1,
    PendingAction.status == "pending",
    PendingAction.action_type == "SMART_ADD_NEGATIVE_KEYWORD",
).limit(5).all()

for a in actions:
    nv = a.new_value or {}
    print(f"Term: {a.keyword}")
    print(f"  confidence col: {a.confidence}")
    print(f"  confidence_score col: {a.confidence_score}")
    print(f"  new_value confidence: {nv.get('confidence')}")
    print(f"  new_value score: {nv.get('confidence_score')}")
    print(f"  reason: {a.reason[:120]}")
    print()
db.close()