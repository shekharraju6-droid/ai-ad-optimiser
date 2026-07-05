"""Report landing page status and old pending action clear counts."""
from backend.db.database import SessionLocal
from backend.db.models import Account, PendingAction
from sqlalchemy import func

db = SessionLocal()

print("=" * 70)
print("LANDING PAGE STATUS")
print("=" * 70)

from backend.db.models import CampaignLandingPage
for name, aid in [("DSU", 1), ("DSI", 2)]:
    rows = db.query(CampaignLandingPage).filter(CampaignLandingPage.account_id == aid).all()
    with_url = sum(1 for r in rows if r.landing_page_url)
    with_content = sum(1 for r in rows if r.landing_page_content)
    print(f"\n{name}:")
    print(f"  Total landing page records: {len(rows)}")
    print(f"  With URL fetched: {with_url}")
    print(f"  With crawled content: {with_content}")
    if rows and with_content:
        sample = rows[0]
        try:
            import json
            content = json.loads(sample.landing_page_content)
            print(f"  Sample summary: {content.get('summary', 'no summary')[:150]}...")
        except Exception:
            print(f"  Sample content: {sample.landing_page_content[:150]}...")

print("\n" + "=" * 70)
print("OLD PENDING ACTIONS WITHOUT CONFIDENCE SCORE")
print("=" * 70)

for name, aid in [("DSU", 1), ("DSI", 2)]:
    total = db.query(PendingAction).filter(
        PendingAction.account_id == aid,
        PendingAction.status == "pending",
    ).count()
    no_conf = db.query(PendingAction).filter(
        PendingAction.account_id == aid,
        PendingAction.status == "pending",
        PendingAction.confidence_score.is_(None),
    ).count()
    with_conf = db.query(PendingAction).filter(
        PendingAction.account_id == aid,
        PendingAction.status == "pending",
        PendingAction.confidence_score.isnot(None),
    ).count()
    print(f"\n{name}:")
    print(f"  Total pending actions: {total}")
    print(f"  WITHOUT confidence score (will be cleared): {no_conf}")
    print(f"  WITH confidence score (will be kept): {with_conf}")

print("\n" + "=" * 70)
print("BUSINESS CONTEXT / NEGATIVE RULES STATUS")
print("=" * 70)
for name in ["DSU", "DSI"]:
    a = db.query(Account).filter(Account.name == name).first()
    print(f"\n{name}:")
    print(f"  business_context length: {len(a.business_context or '')}")
    print(f"  negative_rules length: {len(a.negative_rules or '')}")

db.close()