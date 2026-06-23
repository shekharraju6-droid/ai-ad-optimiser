"""
Seed legacy spend, historical Table 2, and monthly fixed spend tables
from the old Google Ads Excel exports.

DSU: data/DSU_GoogleAds_OldAccount.xlsx (Nov-25 to Mar-26, 18 campaigns)
DSI: data/DSI_GoogleAds_OldAccount.xlsx (Jan-26 to Mar-26, 8 campaigns)

Campaign -> course mapping follows the AI_The_MIS logic (normalized substring
matching with dots/underscores/hyphens stripped).

Run:  python -m backend.scripts.seed_legacy_spend
"""

import openpyxl
from collections import defaultdict
from datetime import date
from typing import Optional

from backend.db.database import Base, engine, SessionLocal
from backend.db import models


# ---------------------------------------------------------------------------
# DSU campaign -> course mapping (exact + fuzzy, from AI_The_MIS)
# ---------------------------------------------------------------------------

DSU_CAMPAIGN_COURSE_MAP = {
    "CHLEAR_BTech_Bangalore_Display_RT": "B.Tech",
    "CHCLEAR_DSU_B_Tech_Bangalore_Search_Ads": "B.Tech",
    "CHCLEAR_DSU_B_Tech_Bangalore_Generic_Search_Ads": "B.Tech",
    "CHCLEAR_DSU_B_Tech_Top _10_Cities_Brand_Search_Ads": "B.Tech",
    "CHCLEAR | DSU | Btech | P Max | Ads": "B.Tech",
    "CHCLEAR | DSU | Btech | P Max | Retargeting ads": "B.Tech",
    "CHCLEAR | DSU | B Tech | Demandge | Bangalore": "B.Tech",
    "CHCLEAR | DSU | B Tech | South states | Search Ads": "B.Tech",
    "CHLEAR | DSU | Pan India | B.tech Ads | 31st Dec": "B.Tech",
    "CHLEAR |DSU | B Tech | Karnataka | Search Ads": "B.Tech",
    "CHLEAR |DSU | B Tech | Bangalore | Search Ads": "B.Tech",
    "Chlear_PMax_BTech_Blr_20260530": "B.Tech",
    "GGL-DSAT": "B.Tech",
    "Direct Traffic": "B.Tech",
    "Pay Per Click Ads": "B.Tech",
    "DSU_MBA_Display_BLR": "MBA",
    "DSU_MBA_Display_RT_BLR": "MBA",
    "CHCLEAR | DSU | MBA | Brand_Search Ads | Jan'26": "MBA",
    "CHCLEAR | DSU | MBA | Search Ads | Jan'26": "MBA",
    "CHLEAR_bba_Bangalore_Brand_Search_Ads": "BBA",
    "CHLEAR | BCA Bangalore | Generic_Search Ads": "BCA",
    "CHLEAR | BCA Bangalore | Brand_Search Ads": "BCA",
    "CHLEAR | BCA Bangalore | Search Ads": "BCA",
    "CHLEAR | BCA Karnataka | Search Ads": "BCA",
    "CHLEAR | DSU| MCA | Disply Ads": "MCA",
    "CHLEAR | DSU| MCA_RT| Disply Ads": "MCA",
    "CHLEAR | DSU | MCA |South States | Search Ad": "MCA",
    "CHLEAR | DSU | MCA | Generic-Search Ad | Jan'26": "MCA",
    "CHCCLEAR | DSU | MCA | Search Ad | Jan'26": "MCA",
    "CHLEAR | DSU | MCA | Brand-Search Ad | Jan'26 #2": "MCA",
    "CHCLEAR | DSU | MCA | P Max Ads -14th Jan'26": "MCA",
    "CHLEAR_msc_cybersecurity_Bangalore_Brand_Search_Ads": "M.Sc Cyber Security",
    "CHLEAR_bsc_cybersecurity_Bangalore_Brand_Search_Ads": "B.Sc Cyber Security",
    "CHCLEAR_Data_Science_MSc_Bangalore_Brand_Search_Ads": "M.Sc Data Science",
    "CHLEAR_Data_Science_BSc_Bangalore_Brand_Search_Ads": "B.Sc Data Science",
    "CHCLEAR_MSc_Biological_Science_Bangalore_Brand_Search_Ads": "M.Sc Biological Sciences",
    "CHLEAR_BSc_Biological_Science_Bangalore_Brand_Search_Ads": "B.Sc Biological Sciences",
    "DSU_B_sc_Cyber_Security_Display_BLR": "B.Sc Cyber Security",
    "DSU_B_sc_Data_Science_Display_BLR": "B.Sc Data Science",
    "CHCLEAR_bcom_Bangalore_Brand_Search_Ads": "B.Com",
    "CHCLEAR | DSU | B Design | Brand_Search Ad April'26": "B.Design",
    "CHCLEAR | DSU | B Design | Search Ad Jan'26": "B.Design",
    "CHCLEAR | DSU | B. Design Retargeting | P Max | Ads": "B.Design",
    "CHCLEAR | DSU | B. Design | P Max | Ads": "B.Design",
    "CHCLEAR | DSU | JMC | Brand_Search Ads Jan'26": "JMC",
    "CHCLEAR | DSU | JMC | Search Ads Jan'26": "JMC",
    "CHCLEAR | DSU | LAW | Bangalore | Brand_Search Ads": "School of Law",
    "CHCLEAR | DSU | LAW | Bangalore | Search Ads": "School of Law",
}

# DSU fuzzy keyword fallback (order matters: more specific first)
DSU_KEYWORDS = [
    ("msc_cybersecurity", "M.Sc Cyber Security"),
    ("msc_cyber", "M.Sc Cyber Security"),
    ("bsc_cybersecurity", "B.Sc Cyber Security"),
    ("bsc_cyber", "B.Sc Cyber Security"),
    ("cyber_security_display", "B.Sc Cyber Security"),
    ("cybersecurity", "B.Sc Cyber Security"),
    ("cyber security", "B.Sc Cyber Security"),
    ("biological_science_bsc", "B.Sc Biological Sciences"),
    ("bsc_biological", "B.Sc Biological Sciences"),
    ("biological_science_msc", "M.Sc Biological Sciences"),
    ("msc_biological", "M.Sc Biological Sciences"),
    ("biological science", "B.Sc Biological Sciences"),
    ("data_science_msc", "M.Sc Data Science"),
    ("msc_data", "M.Sc Data Science"),
    ("data_science_bsc", "B.Sc Data Science"),
    ("bsc_data", "B.Sc Data Science"),
    ("b.sc_data", "B.Sc Data Science"),
    ("data_science_display", "B.Sc Data Science"),
    ("data science s", "B.Sc Data Science"),
    ("b tech", "B.Tech"),
    ("btech", "B.Tech"),
    ("b_tech", "B.Tech"),
    ("b-tech", "B.Tech"),
    ("b.tech", "B.Tech"),
    ("pmax_btech", "B.Tech"),
    ("iit jee", "B.Tech"),
    ("dsat", "B.Tech"),
    ("law", "School of Law"),
    ("llb", "School of Law"),
    ("mba", "MBA"),
    ("bca", "BCA"),
    ("bba", "BBA"),
    ("bcom", "B.Com"),
    ("b.com", "B.Com"),
    ("mca", "MCA"),
    ("b design", "B.Design"),
    ("bdesign", "B.Design"),
    ("b.design", "B.Design"),
    ("jmc", "JMC"),
    ("cjmc", "JMC"),
    ("b pharm", "B.Pharm"),
    ("bpharm", "B.Pharm"),
    ("pharm", "B.Pharm"),
    ("nursing", "B.Sc Nursing"),
    ("bpt", "BPT"),
    ("m.tech", "M.Tech"),
    ("mtech", "M.Tech"),
]


def _normalize(name: str) -> str:
    """Lowercase and strip dots/underscores/hyphens for fuzzy matching."""
    return name.lower().replace(".", "").replace("_", "").replace("-", "")


def map_dsu_campaign(name: str) -> Optional[str]:
    if not name:
        return None
    # Exact match first
    if name in DSU_CAMPAIGN_COURSE_MAP:
        return DSU_CAMPAIGN_COURSE_MAP[name]
    # Fuzzy: try original lower, then normalized
    low = name.lower()
    for kw, course in DSU_KEYWORDS:
        if kw in low:
            return course
    norm = _normalize(name)
    for kw, course in DSU_KEYWORDS:
        if _normalize(kw) in norm:
            return course
    return None


# ---------------------------------------------------------------------------
# DSI campaign -> course mapping (from AI_The_MIS mapCampaignToCourse DSI branch)
# ---------------------------------------------------------------------------

def map_dsi_campaign(name: str) -> Optional[str]:
    if not name:
        return None
    c = _normalize(name)
    if "medical" in c:
        return "Medical Electronics Engineering"
    if "ece" in c or "telecom" in c or "electronicsandcommunication" in c:
        return "Electronics and Communications Engineering"
    if "eee" in c or "electrical" in c:
        return "Electrical and Electronics Engineering"
    if "info" in c or "ise" in c:
        return "Information Science"
    if "automobile" in c or "automotive" in c:
        return "Automotive Engineering"
    if "mech" in c:
        return "Mechanical Engineering"
    if "cse" in c or "computer" in c:
        return "Computer Science"
    if "civil" in c:
        return "Civil Engineering"
    if "chemical" in c:
        return "Chemical Engineering"
    if "biotech" in c:
        return "Biotechnology"
    if "march" in c:
        return "M.Arch"
    c_no_search = c.replace("search", "")
    if "arch" in c_no_search:
        return "B. Arch"
    if "bcaeve" in c or ("bca" in c and "evening" in c):
        return "BCA Evening"
    if "bca" in c:
        return "BCA"
    if "bcomeve" in c or ("bcom" in c and "evening" in c) or ("bcom" in c and "evening" in c):
        return "B.Com Evening"
    if "bcom" in c:
        return "B.Com"
    if "bba" in c:
        return "BBA"
    if "mba" in c:
        return "MBA"
    if "mca" in c:
        return "MCA"
    if "mcom" in c:
        return "M.Com"
    if "bscpcm" in c or "pcm" in c:
        return "B.Sc (PCM)"
    if "bsc" in c:
        return "B.Sc"
    if "dscasc" in c:
        return "DSCASC - UG"
    if "dscads" in c or "dscds" in c or "dsat" in c:
        return "DSCA"
    if "dsca" in c:
        return "DSCA"
    if "dsce" in c or "engg" in c:
        return "DSCE"
    if "dsit" in c or "diploma" in c or "visitourengineeringcollege" in c:
        return "DSIT"
    if "display" in c or "visitour" in c:
        return None  # skip junk
    return name.strip()  # fallback: return original


# DSI department fallback (from getDsiFallbackDept)
DSI_FALLBACK_DEPT = {
    "automobile engineering": "DSCE",
    "biotechnology": "DSCE",
    "chemical engineering": "DSCE",
    "electronics and telecommunication engineering": "DSCE",
    "electronics and telecom engineering": "DSCE",
    "mechanical engineering": "DSCE",
    "eee engineering": "DSCE",
    "medical electronics engineering": "DSCE",
    "electronics and instrumentation engineering": "DSCE",
    "automotive engineering": "DSCE",
    "information science": "DSCE",
    "civil engineering": "DSIT",
    "computer science": "DSIT",
    "computer science and engineering - cyber security": "DSIT",
    "electrical and electronics": "DSIT",
    "electrical and electronics engineering": "DSIT",
    "electronics and communication": "DSIT",
    "electronics and communications engineering": "DSIT",
    "mechanical": "DSIT",
    "diploma": "DSIT",
    "dsit": "DSIT",
    "dsit - diploma": "DSIT",
    "electrical & electronics engineering": "DSIT",
    "bachelor of architecture campus 1": "DSCA",
    "b. arch": "DSCA",
    "m.arch": "DSCA",
    "arch": "DSCA",
    "b.com": "DSCASC - UG",
    "b.com evening": "DSCASC - UG",
    "b.com evening programs": "DSCASC - UG",
    "b.sc (pcm)": "DSCASC - UG",
    "bba": "DSCASC - UG",
    "bca": "DSCASC - UG",
    "bca evening": "DSCASC - UG",
    "bca evening programs": "DSCASC - UG",
    "b.sc": "DSCASC - UG",
    "bca eve": "DSCASC - UG",
    "b.com eve": "DSCASC - UG",
    "mba": "DSCASC - Masters",
    "mca": "DSCASC - Masters",
    "m.com": "DSCASC - Masters",
}


def dsi_dept_for_course(course: str) -> str:
    """Resolve course to department. DSCE/DSIT courses collapse to dept string."""
    if not course:
        return ""
    dept = DSI_FALLBACK_DEPT.get(course.lower().strip())
    if dept in ("DSCE", "DSIT"):
        return dept  # collapse to department
    return course  # keep individual course name


def apply_dsi_override(course: str) -> str:
    """If the resolved course maps to DSCE or DSIT, return the department string."""
    if not course:
        return course
    dept = DSI_FALLBACK_DEPT.get(course.lower().strip())
    if dept in ("DSCE", "DSIT"):
        return dept
    return course


# ---------------------------------------------------------------------------
# Excel parser
# ---------------------------------------------------------------------------

def parse_excel(path: str, map_fn):
    """Parse a Google Ads campaign report Excel file.

    Returns:
        (rows, total_cost, month_totals, campaign_totals, unmapped_campaigns)
        rows: list of (month_str, day_str, campaign, cost_float, mapped_course)
        month_totals: {month_key: total_cost}
        campaign_totals: {campaign_name: total_cost}
        unmapped: list of (campaign_name, cost)
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Sheet1"]
    all_rows = list(ws.iter_rows(min_row=1, values_only=True))
    wb.close()

    header = all_rows[0]
    col = {h: i for i, h in enumerate(header) if h}
    idx_month = col.get("Month")
    idx_day = col.get("Day")
    idx_campaign = col.get("Campaign")
    idx_cost = col.get("Cost")

    parsed_rows = []
    total_cost = 0.0
    month_totals = defaultdict(float)
    campaign_totals = defaultdict(float)
    unmapped = []

    for r in all_rows[1:]:
        cost_val = r[idx_cost]
        if cost_val is None or cost_val == "":
            continue
        try:
            cost = float(cost_val)
        except (TypeError, ValueError):
            continue
        if cost == 0:
            continue

        total_cost += cost
        campaign = str(r[idx_campaign] or "").strip()
        month_val = str(r[idx_month] or "")[:7]  # YYYY-MM
        day_val = str(r[idx_day] or "")[:10]
        month_totals[month_val] += cost
        campaign_totals[campaign] += cost

        mapped = map_fn(campaign)
        if not mapped:
            unmapped.append((campaign, cost))

        parsed_rows.append({
            "month": month_val,
            "day": day_val,
            "campaign": campaign,
            "cost": cost,
            "course": mapped,
        })

    return parsed_rows, total_cost, dict(month_totals), dict(campaign_totals), unmapped


# ---------------------------------------------------------------------------
# DB seeding
# ---------------------------------------------------------------------------

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_key_to_mmm_yyyy(ym: str) -> str:
    """Convert '2025-11' -> 'Nov-2025'."""
    try:
        y, m = ym.split("-")
        return f"{MONTH_NAMES[int(m) - 1]}-{y}"
    except (ValueError, IndexError):
        return ym


def seed_dsu(path: str):
    print("\n=== Seeding DSU ===")
    rows, total, month_totals, campaign_totals, unmapped = parse_excel(path, map_dsu_campaign)

    print(f"Parsed {len(rows)} non-zero spend rows")
    print(f"Total cost: â‚¹{total:.2f}")
    print(f"Months: {sorted(month_totals.keys())}")
    print(f"Unique campaigns: {len(campaign_totals)}")
    if unmapped:
        print(f"WARNING: {len(unmapped)} unmapped campaigns:")
        for name, cost in unmapped:
            print(f"  {name}: â‚¹{cost:.2f}")
    else:
        print("All campaigns mapped successfully!")

    # Aggregate by course x month
    course_month_spend = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if r["course"]:
            course_month_spend[r["course"]][r["month"]] += r["cost"]

    db = SessionLocal()
    try:
        # Clear existing
        db.query(models.DsuLegacySpend).delete()
        db.query(models.DsuTable2Historical).delete()
        db.query(models.DsuMonthlySpendFixed).delete()
        db.flush()

        # Seed dsu_legacy_spend (course x month)
        legacy_count = 0
        for course, months in course_month_spend.items():
            for month, spend in months.items():
                db.add(models.DsuLegacySpend(
                    month=month,
                    course=course,
                    spend=round(spend, 2),
                    leads=0,  # leads come from LSQ mirror, not this Excel
                ))
                legacy_count += 1
        print(f"Seeded dsu_legacy_spend: {legacy_count} rows")

        # Seed dsu_monthly_spend_fixed (month -> total Google spend, no GST)
        fixed_count = 0
        for month, spend in sorted(month_totals.items()):
            mk = month_key_to_mmm_yyyy(month)
            db.add(models.DsuMonthlySpendFixed(
                month_key=mk,
                google_spend=round(spend, 2),
            ))
            fixed_count += 1
        print(f"Seeded dsu_monthly_spend_fixed: {fixed_count} rows")

        # Seed dsu_table2_historical (course -> total spend across all months)
        # This is the cumulative spend from the old account only.
        # The live API spend (new account) is NOT included here â€” it will be
        # added by the live route when computing the default range.
        # For now, store the old-account cumulative per course.
        hist_count = 0
        for course, months in course_month_spend.items():
            total_spend = sum(months.values())
            db.add(models.DsuTable2Historical(
                course=course,
                leads=0,  # leads come from LSQ mirror
                spend=round(total_spend, 2),
            ))
            hist_count += 1
        print(f"Seeded dsu_table2_historical (old-account only): {hist_count} rows")
        print(f"  NOTE: Live API spend (new account) will be added by the route.")
        print(f"  Current historical total: â‚¹{sum(sum(m.values()) for m in course_month_spend.values()):.2f}")

        db.commit()
        print("DSU seeding complete!")
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


def seed_dsi(path: str):
    print("\n=== Seeding DSI ===")
    rows, total, month_totals, campaign_totals, unmapped = parse_excel(path, map_dsi_campaign)

    print(f"Parsed {len(rows)} non-zero spend rows")
    print(f"Total cost: â‚¹{total:.2f}")
    print(f"Months: {sorted(month_totals.keys())}")
    print(f"Unique campaigns: {len(campaign_totals)}")
    if unmapped:
        print(f"Unmapped campaigns (returned as-is): {len(unmapped)}")
        for name, cost in unmapped:
            print(f"  {name}: â‚¹{cost:.2f}")

    # Apply DSI department override: DSCE/DSIT courses collapse to dept string
    course_month_spend = defaultdict(lambda: defaultdict(float))
    for r in rows:
        course = r["course"]
        if not course:
            continue
        # Apply DSI override: if course maps to DSCE/DSIT, use dept as the key
        resolved = apply_dsi_override(course)
        course_month_spend[resolved][r["month"]] += r["cost"]

    db = SessionLocal()
    try:
        # Clear existing
        db.query(models.DsiLegacySpend).delete()
        db.query(models.DsiTable2Historical).delete()
        db.query(models.DsiMonthlySpendFixed).delete()
        db.flush()

        # Seed dsi_legacy_spend
        legacy_count = 0
        for course, months in course_month_spend.items():
            for month, spend in months.items():
                db.add(models.DsiLegacySpend(
                    month=month,
                    course=course,
                    spend=round(spend, 2),
                    leads=0,
                ))
                legacy_count += 1
        print(f"Seeded dsi_legacy_spend: {legacy_count} rows")

        # Seed dsi_monthly_spend_fixed
        fixed_count = 0
        for month, spend in sorted(month_totals.items()):
            mk = month_key_to_mmm_yyyy(month)
            db.add(models.DsiMonthlySpendFixed(
                month_key=mk,
                google_spend=round(spend, 2),
            ))
            fixed_count += 1
        print(f"Seeded dsi_monthly_spend_fixed: {fixed_count} rows")

        # Seed dsi_table2_historical (old-account cumulative per course)
        hist_count = 0
        for course, months in course_month_spend.items():
            total_spend = sum(months.values())
            dept = dsi_dept_for_course(course)
            db.add(models.DsiTable2Historical(
                course=course,
                department=dept,
                leads=0,
                spend=round(total_spend, 2),
            ))
            hist_count += 1
        print(f"Seeded dsi_table2_historical (old-account only): {hist_count} rows")

        db.commit()
        print("DSI seeding complete!")
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Creating tables...")
    Base.metadata.create_all(bind=engine, tables=[
        models.DsuLegacySpend.__table__,
        models.DsuTable2Historical.__table__,
        models.DsuMonthlySpendFixed.__table__,
        models.DsiLegacySpend.__table__,
        models.DsiTable2Historical.__table__,
        models.DsiMonthlySpendFixed.__table__,
    ])

    seed_dsu(r"data/DSU_GoogleAds_OldAccount.xlsx")
    seed_dsi(r"data/DSI_GoogleAds_OldAccount.xlsx")

    print("\n=== Summary ===")
    db = SessionLocal()
    try:
        dsu_legacy = db.query(models.DsuLegacySpend).all()
        dsu_hist = db.query(models.DsuTable2Historical).all()
        dsu_fixed = db.query(models.DsuMonthlySpendFixed).all()
        dsi_legacy = db.query(models.DsiLegacySpend).all()
        dsi_hist = db.query(models.DsiTable2Historical).all()
        dsi_fixed = db.query(models.DsiMonthlySpendFixed).all()

        print(f"DSU legacy_spend: {len(dsu_legacy)} rows, total â‚¹{sum(r.spend for r in dsu_legacy):.2f}")
        print(f"DSU table2_historical: {len(dsu_hist)} rows, total â‚¹{sum(r.spend for r in dsu_hist):.2f}")
        print(f"DSU monthly_spend_fixed: {len(dsu_fixed)} rows, total â‚¹{sum(r.google_spend for r in dsu_fixed):.2f}")
        print(f"DSI legacy_spend: {len(dsi_legacy)} rows, total â‚¹{sum(r.spend for r in dsi_legacy):.2f}")
        print(f"DSI table2_historical: {len(dsi_hist)} rows, total â‚¹{sum(r.spend for r in dsi_hist):.2f}")
        print(f"DSI monthly_spend_fixed: {len(dsi_fixed)} rows, total â‚¹{sum(r.google_spend for r in dsi_fixed):.2f}")
    finally:
        db.close()
    print("\nDone!")