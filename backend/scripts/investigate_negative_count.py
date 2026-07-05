"""Investigate discrepancy in Negative Keywords count and confidence data."""
from backend.db.database import SessionLocal
from backend.db.models import Account, PendingAction

db = SessionLocal()

dsu = db.query(Account).filter(Account.name == "DSU").first()
print(f"DSU account id={dsu.id if dsu else 'NOT FOUND'}")
print()

# Count all pending actions for DSU
all_pending = db.query(PendingAction).filter(
    PendingAction.account_id == dsu.id,
    PendingAction.status == "pending",
).count()
print(f"Total pending actions for DSU: {all_pending}")

# Count by action type
from sqlalchemy import func
rows = db.query(PendingAction.action_type, func.count(PendingAction.id)).filter(
    PendingAction.account_id == dsu.id,
    PendingAction.status == "pending",
).group_by(PendingAction.action_type).all()
print("\nBy action type:")
for action_type, count in rows:
    print(f"  {action_type}: {count}")

# Specifically negative keyword types
neg_types = ["SMART_ADD_NEGATIVE_KEYWORD", "ADD_NEGATIVE_KEYWORD"]
neg_count = db.query(PendingAction).filter(
    PendingAction.account_id == dsu.id,
    PendingAction.status == "pending",
    PendingAction.action_type.in_(neg_types),
).count()
print(f"\nTotal negative keyword actions (raw): {neg_count}")

# Why 1520? Maybe the UI tab count comes from the review endpoint
from backend.routes.audits import _merge_search_term_actions, _fetch_campaign_name_map
campaign_name_map = _fetch_campaign_name_map(dsu)
neg_actions = db.query(PendingAction).filter(
    PendingAction.account_id == dsu.id,
    PendingAction.status == "pending",
    PendingAction.action_type.in_(neg_types),
).all()
merged = _merge_search_term_actions(neg_actions, campaign_name_map)
print(f"Merged negative keyword rows: {len(merged)}")

# Check confidence values
conf_values = db.query(PendingAction.confidence, func.count(PendingAction.id)).filter(
    PendingAction.account_id == dsu.id,
    PendingAction.status == "pending",
    PendingAction.action_type.in_(neg_types),
).group_by(PendingAction.confidence).all()
print("\nConfidence distribution in raw actions:")
for conf, count in conf_values:
    print(f"  {conf}: {count}")

# Check created_at - when were these actions generated?
from datetime import datetime, timedelta
recent = db.query(PendingAction).filter(
    PendingAction.account_id == dsu.id,
    PendingAction.status == "pending",
    PendingAction.action_type.in_(neg_types),
).order_by(PendingAction.created_at.desc()).first()
oldest = db.query(PendingAction).filter(
    PendingAction.account_id == dsu.id,
    PendingAction.status == "pending",
    PendingAction.action_type.in_(neg_types),
).order_by(PendingAction.created_at.asc()).first()
if recent:
    print(f"\nMost recent negative action: {recent.created_at}")
    print(f"Oldest negative action: {oldest.created_at}")

db.close()