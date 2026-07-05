"""Count pending actions with numeric campaign names in new_value JSON."""
import json
from backend.db.database import SessionLocal
from backend.db.models import PendingAction

db = SessionLocal()
rows = db.query(PendingAction).filter(PendingAction.status == "pending").all()
numeric_count = 0
for r in rows:
    nv = r.new_value
    if isinstance(nv, dict):
        cn = nv.get("campaign_name", "")
        if cn and str(cn).strip().isdigit():
            numeric_count += 1
print(f"Found {numeric_count} pending actions with numeric campaign_name (out of {len(rows)} total)")
db.close()