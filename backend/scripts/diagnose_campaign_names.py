"""Diagnostic: show distribution of campaign_name values in pending_actions new_value."""
from collections import Counter
from backend.db.database import SessionLocal
from backend.db.models import PendingAction

db = SessionLocal()
rows = db.query(PendingAction).filter(PendingAction.status == "pending").all()
empty_count = 0
numeric_count = 0
named_count = 0
sample_names = []
for r in rows:
    nv = r.new_value
    if isinstance(nv, dict):
        cn = nv.get("campaign_name", "")
        if not cn:
            empty_count += 1
        elif str(cn).strip().isdigit():
            numeric_count += 1
            if len(sample_names) < 5:
                sample_names.append(("numeric", cn, r.campaign_id))
        else:
            named_count += 1
            if len(sample_names) < 10:
                sample_names.append(("named", cn, r.campaign_id))
print(f"Empty: {empty_count}, Numeric: {numeric_count}, Named: {named_count}")
print("Samples:")
for s in sample_names:
    print(f"  {s}")
db.close()