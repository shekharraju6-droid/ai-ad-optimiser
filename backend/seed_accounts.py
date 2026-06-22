"""
Seed the 9 real ChlearSakhaaOps AI client accounts with groups.
Run: python -m backend.seed_accounts
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db.database import SessionLocal, init_db
from backend.db.models import Account, AccountGroup, AccountType, AccountStatus

def seed():
    init_db()
    db = SessionLocal()

    existing = db.query(Account).first()
    if existing:
        print(f"Accounts already exist (found id={existing.id}). Skipping seed.")
        db.close()
        return

    # Create groups
    groups_data = [
        {"name": "Education"},
        {"name": "Real Estate"},
        {"name": "Steel / Manufacturing"},
        {"name": "Healthcare"},
        {"name": "Fitness / Lifestyle"},
        {"name": "Fire Safety & Security Systems"},
    ]
    group_map = {}
    for g in groups_data:
        obj = AccountGroup(name=g["name"])
        db.add(obj)
        db.flush()
        group_map[g["name"]] = obj.id

    # Create 9 real accounts
    accounts_data = [
        {
            "name": "DSU",
            "group": "Education",
            "account_type": AccountType.GOOGLE,
            "external_id": "290-991-9094",
            "has_google": True, "has_meta": False,
            "google_external_id": "290-991-9094",
            "google_is_live": True, "meta_is_live": False,
            "is_live": True,
            "google_client_id": None,
            "google_client_secret": None,
            "google_developer_token": None,
            "redirect_base_url": "http://127.0.0.1:8000",
            "status": AccountStatus.WARNING,
            "spend": 80556.0, "conversions": 22.0, "clicks": 2931.0, "impressions": 123102.0,
            "ctr": 2.38, "cpa": 3661.64, "budget": 89646.13, "budget_used_pct": 89.86,
            "last_sync_error": "Invalid credentials or connector not configured",
        },
        {
            "name": "DSI",
            "group": "Education",
            "account_type": AccountType.BOTH,
            "external_id": "dsi-google",
            "has_google": True, "has_meta": True,
            "google_external_id": "dsi-google",
            "google_is_live": False, "meta_is_live": False,
            "is_live": False,
            "status": AccountStatus.WARNING,
            "spend": 30549.0, "conversions": 210.0, "clicks": 317.0, "impressions": 14899.0,
            "ctr": 2.13, "cpa": 145.47, "budget": 39520.81, "budget_used_pct": 77.3,
        },
        {
            "name": "Shyam Steel",
            "group": "Steel / Manufacturing",
            "account_type": AccountType.BOTH,
            "external_id": "shyam-steel-google",
            "has_google": True, "has_meta": True,
            "google_external_id": "shyam-steel-google",
            "google_is_live": False, "meta_is_live": False,
            "is_live": False,
            "status": AccountStatus.HEALTHY,
            "spend": 85454.0, "conversions": 257.0, "clicks": 856.0, "impressions": 39376.0,
            "ctr": 2.17, "cpa": 332.51, "budget": 122432.5, "budget_used_pct": 69.8,
        },
        {
            "name": "Mantri Developers",
            "group": "Real Estate",
            "account_type": AccountType.GOOGLE,
            "external_id": "mantri-developers-google",
            "has_google": True, "has_meta": False,
            "google_external_id": "mantri-developers-google",
            "google_is_live": False, "meta_is_live": False,
            "is_live": False,
            "status": AccountStatus.WARNING,
            "spend": 24032.0, "conversions": 43.0, "clicks": 2932.0, "impressions": 158328.0,
            "ctr": 1.85, "cpa": 558.88, "budget": 28131.29, "budget_used_pct": 85.43,
        },
        {
            "name": "Classic Featherlite (CF)",
            "group": "Real Estate",
            "account_type": AccountType.GOOGLE,
            "external_id": "classic-featherlite-google",
            "has_google": True, "has_meta": False,
            "google_external_id": "classic-featherlite-google",
            "google_is_live": False, "meta_is_live": False,
            "is_live": False,
            "status": AccountStatus.WARNING,
            "spend": 32578.0, "conversions": 225.0, "clicks": 3943.0, "impressions": 149834.0,
            "ctr": 2.63, "cpa": 144.79, "budget": 44350.15, "budget_used_pct": 73.46,
        },
        {
            "name": "Sparsh Hospitals",
            "group": "Healthcare",
            "account_type": AccountType.GOOGLE,
            "external_id": "sparsh-hospitals-google",
            "has_google": True, "has_meta": False,
            "google_external_id": "sparsh-hospitals-google",
            "google_is_live": False, "meta_is_live": False,
            "is_live": False,
            "status": AccountStatus.WARNING,
            "spend": 11596.0, "conversions": 272.0, "clicks": 890.0, "impressions": 54290.0,
            "ctr": 1.64, "cpa": 42.63, "budget": 16130.76, "budget_used_pct": 71.89,
        },
        {
            "name": "IFS",
            "group": "Fire Safety & Security Systems",
            "account_type": AccountType.GOOGLE,
            "external_id": "ifs-google",
            "has_google": True, "has_meta": False,
            "google_external_id": "ifs-google",
            "google_is_live": False, "meta_is_live": False,
            "is_live": False,
            "status": AccountStatus.WARNING,
            "spend": 112935.0, "conversions": 5.0, "clicks": 3854.0, "impressions": 242802.0,
            "ctr": 1.59, "cpa": 22587.0, "budget": 156572.4, "budget_used_pct": 72.13,
        },
        {
            "name": "The Little Gym (TLG)",
            "group": "Fitness / Lifestyle",
            "account_type": AccountType.META,
            "external_id": "tlg-meta",
            "has_google": False, "has_meta": True,
            "meta_external_id": "tlg-meta",
            "google_is_live": False, "meta_is_live": False,
            "is_live": False,
            "status": AccountStatus.HEALTHY,
            "spend": 29343.0, "conversions": 117.0, "clicks": 655.0, "impressions": 29475.0,
            "ctr": 2.22, "cpa": 250.79, "budget": 41982.4, "budget_used_pct": 69.89,
        },
        {
            "name": "Surya Developers",
            "group": "Real Estate",
            "account_type": AccountType.GOOGLE,
            "external_id": "surya-developers-google",
            "has_google": True, "has_meta": False,
            "google_external_id": "surya-developers-google",
            "google_is_live": False, "meta_is_live": False,
            "is_live": False,
            "status": AccountStatus.WARNING,
            "spend": 145405.0, "conversions": 102.0, "clicks": 4038.0, "impressions": 250356.0,
            "ctr": 1.61, "cpa": 1425.54, "budget": 186001.49, "budget_used_pct": 78.17,
        },
    ]

    for ad in accounts_data:
        group_name = ad.pop("group")
        group_id = group_map.get(group_name)
        acc = Account(
            group_id=group_id,
            currency="INR",
            timezone="Asia/Kolkata",
            refresh_interval_minutes=60,
            audit_interval_minutes=60,
            is_active=True,
            **ad,
        )
        db.add(acc)

    db.commit()
    count = db.query(Account).count()
    print(f"Seeded {count} accounts across {len(groups_data)} groups.")
    db.close()

if __name__ == "__main__":
    seed()