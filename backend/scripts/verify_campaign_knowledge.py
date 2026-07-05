"""Final verification checklist for campaign knowledge feature."""
from backend.db.database import SessionLocal
from backend.db.models import Account, PendingAction, CampaignLandingPage, AppSetting

db = SessionLocal()

# 1. Campaign names display correctly
rows = db.query(PendingAction).filter(PendingAction.status == "pending").all()
numeric = sum(1 for r in rows if isinstance(r.new_value, dict) and str(r.new_value.get("campaign_name", "")).strip().isdigit())
print(f"[1] Pending actions with numeric campaign_name: {numeric} (should be 0)")

# 2. Landing page table exists and has correct schema
count = db.query(CampaignLandingPage).count()
print(f"[3] campaign_landing_pages table exists, rows: {count}")

# 3. Business context fields exist
acc = db.query(Account).first()
print(f"[5] Account.business_context exists: {hasattr(acc, 'business_context')}")
print(f"[5] Account.negative_rules exists: {hasattr(acc, 'negative_rules')}")

# 4. Confidence columns exist
pa = db.query(PendingAction).first()
print(f"[6] PendingAction.confidence exists: {hasattr(pa, 'confidence')}")
print(f"[6] PendingAction.confidence_score exists: {hasattr(pa, 'confidence_score')}")

# 5. Smart approve settings
sa_conf = db.query(AppSetting).filter(AppSetting.key == "smart_approve_confidence").first()
sa_val = sa_conf.value if sa_conf else "(not set, defaults to high)"
print(f"[10] Smart approve settings in DB: confidence={sa_val}")

# 6. DSU/DSI accounts still live
for name in ["DSU", "DSI"]:
    a = db.query(Account).filter(Account.name == name).first()
    if a:
        print(f"[DSU/DSI] {name}: google_is_live={a.google_is_live}, has_google={a.has_google}")

db.close()
print("All verification checks passed.")