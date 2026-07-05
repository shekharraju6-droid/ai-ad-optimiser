"""Update DSU and DSI AI Knowledge and refresh landing pages."""
from backend.db.database import SessionLocal
from backend.db.models import Account
from backend.services.landing_page_service import fetch_campaign_landing_pages, crawl_stale_landing_pages

db = SessionLocal()

DSU_CONTEXT = """DSU (Dayananda Sagar University) is a private university in Bangalore, Karnataka, India.
Programs include B.Tech, MBA, BCA, BSc, MSc, Law and other UG/PG programs.
All programs are full-time, on-campus in Bangalore.
Fees range from 2 to 8 lakhs per year depending on program.
Target audience: students and parents in Karnataka and South Indian states seeking UG/PG admission.
Managed by CHLEAR (CHL Marketing Solutions). CRM: LeadSquared.
Website: dsu.edu.in. Campuses include Kudlu Gate, Harohalli, City Campus."""

DSU_NEGATIVE_RULES = """Does NOT offer free courses or free education
Does NOT offer distance learning or online degrees
Does NOT offer part-time programs
Does NOT offer government quota seats directly
Does NOT provide 100% scholarship or full fee waiver
Not related to: jobs at DSU, recruitment, faculty hiring, non-teaching staff
Not related to: salary packages, employee reviews, Glassdoor
Competitors: Christ University, PES University, REVA University, Jain University, BMS College, RV College, Alliance University, Presidency University, CMR University
Irrelevant intents: download question papers, previous year papers, exam results, hall ticket, student login, ERP login, attendance portal
Irrelevant: CET counselling dates, KCET cutoff, COMEDK results"""

DSI_CONTEXT = """DSI (Dayananda Sagar Institutions) is a group of private educational institutions in Bangalore, Karnataka, India.
It includes multiple constituent colleges:
- DSCE (Dayananda Sagar College of Engineering) — B.Tech, M.Tech programs
- DSATM (Dayananda Sagar Academy of Technology and Management) — Engineering programs
- DSCASC (Dayananda Sagar College of Arts, Science and Commerce) — BCA, B.Com, BBA, B.Sc, B.Arch, BA programs
- DSIT (Dayananda Sagar Institute of Technology) — Diploma programs after 10th
- DSPS (Dayananda Sagar Pre-University) — PUC/11th-12th
Programs: B.Tech, BCA, B.Com, BBA, B.Sc, B.Arch, BA, Diploma (after 10th), MBA, MCA, M.Tech.
All programs are full-time, on-campus in Bangalore.
Fees range 1 to 6 lakhs per year depending on program and college.
Target audience: Students and parents in Karnataka and South Indian states seeking UG/PG/Diploma admission.
Diploma campaigns target students completing 10th standard. UG campaigns target 12th/PUC completers.
Ad platforms: Google Ads. PPC managed by CHLEAR (CHL Marketing Solutions). CRM: LeadSquared."""

DSI_NEGATIVE_RULES = """Does NOT offer free courses or free education
Does NOT offer distance learning or online degrees
Does NOT offer part-time programs
Does NOT offer government quota seats directly
Does NOT provide 100% scholarship or full fee waiver
Not related to: jobs at DSI, recruitment, faculty hiring, non-teaching staff
Not related to: salary packages, employee reviews, Glassdoor
Not related to: DSCE/DSATM admission when campaign is specifically for DSIT Diploma
Not related to: degree programs (B.Tech/BCA/MBA) when campaign is specifically for Diploma
Competitors: Christ University, PES University, REVA University, Jain University, BMS College, RV College, Alliance University, Presidency University, CMR University
Irrelevant intents: download question papers, previous year papers, exam results, hall ticket, student login, ERP login, attendance portal
Irrelevant: CET counselling dates, KCET cutoff, COMEDK results
Cross-campaign rule: Diploma campaign should NOT capture degree-level search terms and vice versa"""

updates = {
    "DSU": {"context": DSU_CONTEXT, "rules": DSU_NEGATIVE_RULES},
    "DSI": {"context": DSI_CONTEXT, "rules": DSI_NEGATIVE_RULES},
}

results = {}
for name, data in updates.items():
    account = db.query(Account).filter(Account.name == name).first()
    if not account:
        print(f"{name}: account not found")
        continue
    was_empty_ctx = not (account.business_context or "").strip()
    was_empty_rules = not (account.negative_rules or "").strip()
    account.business_context = data["context"]
    account.negative_rules = data["rules"]
    db.commit()
    results[name] = {
        "id": account.id,
        "context_updated": was_empty_ctx,
        "rules_updated": was_empty_rules,
    }
    print(f"{name}: updated business_context and negative_rules (were_empty: ctx={was_empty_ctx}, rules={was_empty_rules})")

# Refresh landing pages for both
print("\n--- Refreshing landing pages ---")
for name in ["DSU", "DSI"]:
    account = db.query(Account).filter(Account.name == name).first()
    if not account:
        continue
    print(f"\n{name}: fetching landing pages...")
    fetch_result = fetch_campaign_landing_pages(account.id, db=db)
    print(f"  fetch: {fetch_result}")
    print(f"{name}: crawling stale landing pages...")
    crawl_result = crawl_stale_landing_pages(account.id, db=db)
    print(f"  crawl: {crawl_result}")

db.close()
print("\nDone.")