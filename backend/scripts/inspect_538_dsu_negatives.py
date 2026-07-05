"""Inspect the 538 DSU negative keyword rows currently in the review modal."""
import json
from backend.db.database import SessionLocal
from backend.db.models import Account, PendingAction
from backend.routes.audits import _merge_search_term_actions, _fetch_campaign_name_map

db = SessionLocal()

dsu = db.query(Account).filter(Account.name == "DSU").first()
actions = db.query(PendingAction).filter(
    PendingAction.account_id == dsu.id,
    PendingAction.status == "pending",
    PendingAction.action_type.in_(("SMART_ADD_NEGATIVE_KEYWORD", "ADD_NEGATIVE_KEYWORD")),
).all()

print(f"DSU raw negative actions: {len(actions)}")

campaign_name_map = _fetch_campaign_name_map(dsu)
merged = _merge_search_term_actions(actions, campaign_name_map)
print(f"Merged display rows: {len(merged)}")

# Show confidence distribution
high = [m for m in merged if (m.get("confidence") or "MEDIUM").upper() == "HIGH"]
medium = [m for m in merged if (m.get("confidence") or "MEDIUM").upper() == "MEDIUM"]
low = [m for m in merged if (m.get("confidence") or "MEDIUM").upper() == "LOW"]
print(f"High: {len(high)} | Medium: {len(medium)} | Low: {len(low)}")

# Show first 20 rows that would appear when Filter: High is selected
print("\n=== First 20 rows (what should render) ===")
for i, m in enumerate(merged[:20], 1):
    print(f"{i}. {m['search_term']}")
    print(f"   Campaign: {m['campaign_name']}")
    print(f"   Confidence: {m['confidence']} ({m['confidence_score']})")
    print(f"   Spend: INR {m.get('spend', 0):,.2f} | Clicks: {m.get('clicks', 0)}")
    print()

# Check if filter High hides everything
print(f"\nWith Filter: High applied, visible rows would be: {len(high)}")
print(f"With Filter: All applied, visible rows would be: {len(merged)}")

db.close()