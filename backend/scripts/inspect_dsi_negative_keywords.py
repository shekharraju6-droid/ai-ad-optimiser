"""Inspect DSI negative keyword audit data for live review."""
from backend.db.database import SessionLocal
from backend.db.models import Account, PendingAction
from backend.routes.audits import _merge_search_term_actions, _fetch_campaign_name_map
from sqlalchemy import func
from datetime import datetime

db = SessionLocal()

dsi = db.query(Account).filter(Account.name == "DSI").first()
if not dsi:
    print("DSI account not found")
    db.close()
    exit()

print(f"Account: {dsi.name} (id={dsi.id})")
print(f"Business context: {bool(dsi.business_context)}")
print(f"Negative rules: {bool(dsi.negative_rules)}")
print()

# Count by action type
rows = db.query(PendingAction.action_type, func.count(PendingAction.id)).filter(
    PendingAction.account_id == dsi.id,
    PendingAction.status == "pending",
).group_by(PendingAction.action_type).all()
print(f"Total pending actions for DSI: {sum(c for _, c in rows)}")
print("\nBy action type:")
for action_type, count in rows:
    print(f"  {action_type}: {count}")

# Specifically negative keyword types
neg_types = ["SMART_ADD_NEGATIVE_KEYWORD", "ADD_NEGATIVE_KEYWORD"]
neg_actions = db.query(PendingAction).filter(
    PendingAction.account_id == dsi.id,
    PendingAction.status == "pending",
    PendingAction.action_type.in_(neg_types),
).all()
print(f"\nTotal negative keyword actions (raw): {len(neg_actions)}")

# Check real metrics
zero_spend = sum(1 for a in neg_actions if (a.new_value or {}).get("metrics", {}).get("spend", 0) == 0)
zero_clicks = sum(1 for a in neg_actions if (a.new_value or {}).get("metrics", {}).get("clicks", 0) == 0)
with_confidence = sum(1 for a in neg_actions if a.confidence)
with_score = sum(1 for a in neg_actions if a.confidence_score)
new_style = sum(1 for a in neg_actions if a.action_type == "SMART_ADD_NEGATIVE_KEYWORD")
old_style = sum(1 for a in neg_actions if a.action_type == "ADD_NEGATIVE_KEYWORD")

print(f"Actions with zero spend: {zero_spend}")
print(f"Actions with zero clicks: {zero_clicks}")
print(f"Actions with confidence column set: {with_confidence}")
print(f"Actions with confidence_score set: {with_score}")
print(f"New-style SMART_ADD_NEGATIVE_KEYWORD: {new_style}")
print(f"Old-style ADD_NEGATIVE_KEYWORD: {old_style}")
print()

# Merge like the review endpoint does
campaign_name_map = _fetch_campaign_name_map(dsi)
merged = _merge_search_term_actions(neg_actions, campaign_name_map)
print(f"Merged rows for display: {len(merged)}")
print()

# Sort by confidence descending, then spend descending
merged.sort(key=lambda i: (-(i.get("confidence_score") or 0), -(i.get("spend") or 0)))

print("=" * 80)
print("SAMPLE: top 15 merged rows by confidence")
print("=" * 80)
for i, m in enumerate(merged[:15], 1):
    print(f"\n{i}. {m['search_term']}")
    print(f"   Campaign: {m['campaign_name']}")
    print(f"   Spend: INR {m.get('spend', 0):,.2f} | Clicks: {m.get('clicks', 0)} | Conversions: {m.get('conversions', 0)}")
    print(f"   Confidence: {m['confidence']} ({m['confidence_score']})")
    reason = (m.get('findings') or [{}])[0].get('detail', '') if m.get('findings') else ''
    print(f"   Reason: {reason}")

print("\n" + "=" * 80)
print("CONFIDENCE DISTRIBUTION")
print("=" * 80)
high = [m for m in merged if (m['confidence'] or 'MEDIUM').upper() == 'HIGH']
medium = [m for m in merged if (m['confidence'] or 'MEDIUM').upper() == 'MEDIUM']
low = [m for m in merged if (m['confidence'] or 'MEDIUM').upper() == 'LOW']
print(f"High: {len(high)} | Medium: {len(medium)} | Low: {len(low)}")

print("\n" + "=" * 80)
print("FIRST 5 HIGH CONFIDENCE ITEMS (for manual verification)")
print("=" * 80)
for i, m in enumerate(high[:5], 1):
    print(f"\n{i}. {m['search_term']}")
    print(f"   Campaign: {m['campaign_name']}")
    print(f"   Spend: INR {m.get('spend', 0):,.2f} | Clicks: {m.get('clicks', 0)}")
    print(f"   Confidence: {m['confidence']} ({m['confidence_score']})")
    reason = (m.get('findings') or [{}])[0].get('detail', '') if m.get('findings') else ''
    print(f"   Reason: {reason}")

print("\n" + "=" * 80)
print("FIRST 3 MEDIUM/LOW CONFIDENCE ITEMS (for uncertainty check)")
print("=" * 80)
uncertain = medium[:2] + low[:1]
for i, m in enumerate(uncertain, 1):
    print(f"\n{i}. {m['search_term']}")
    print(f"   Campaign: {m['campaign_name']}")
    print(f"   Spend: INR {m.get('spend', 0):,.2f} | Clicks: {m.get('clicks', 0)}")
    print(f"   Confidence: {m['confidence']} ({m['confidence_score']})")
    reason = (m.get('findings') or [{}])[0].get('detail', '') if m.get('findings') else ''
    print(f"   Reason: {reason}")

# Simulate Smart Approve
print("\n" + "=" * 80)
print("SMART APPROVE SIMULATION: HIGH, max spend INR 500, zero conversions")
print("=" * 80)
smart_items = [m for m in merged
               if (m['confidence'] or '').upper() == 'HIGH'
               and (m.get('spend') or 0) <= 500
               and (m.get('conversions') or 0) == 0]
print(f"Preview count: {len(smart_items)} of {len(merged)} items")
for m in smart_items[:10]:
    print(f"  - {m['search_term']} (spend INR {m.get('spend', 0):,.2f}, clicks {m.get('clicks', 0)})")

# Check landing page content availability
print("\n" + "=" * 80)
print("LANDING PAGE CONTENT AVAILABILITY")
print("=" * 80)
from backend.db.models import CampaignLandingPage
lp_rows = db.query(CampaignLandingPage).filter(CampaignLandingPage.account_id == dsi.id).all()
with_summary = sum(1 for r in lp_rows if r.landing_page_content)
with_url = sum(1 for r in lp_rows if r.landing_page_url)
print(f"Landing page records: {len(lp_rows)}")
print(f"With URL: {with_url}, with crawled content: {with_summary}")

# Check created_at range
if neg_actions:
    recent = max(a.created_at for a in neg_actions)
    oldest = min(a.created_at for a in neg_actions)
    print(f"\nNegative action date range: {oldest} to {recent}")

db.close()