"""
Live data fetcher for DSI course performance report.
Pulls campaign spend from Google Ads API and leads from LeadSquared.
Maps both to the DSI department/course taxonomy with department rollup.
"""
import json
import sqlite3
import logging
from datetime import date, timedelta
from collections import defaultdict
from typing import Dict, Any, List, Optional

from backend.services.crypto import decrypt

logger = logging.getLogger("AdOptima")

DSI_ACCOUNT_ID = 2
DSI_CUSTOMER_ID = "1917462211"
DSI_INCEPTION = "2025-11-28"
DSI_GST_TRANSITION = "2026-06-19"
GST_MULTIPLIER = 1.18

# DSI Department Sort Order
DEPT_ORDER = {
    "dsit": 2,
    "dsce": 3,
    "dsca": 4,
    "dscasc - ug": 5,
    "dscasc - masters": 6,
}

# DSI Course list (after department rollup, these are the row labels)
DSI_COURSES = [
    "DSCE", "DSIT",
    "B. Arch", "Bachelor of Architecture Campus 1", "M.Arch",
    "B.Com", "B.Com Evening Programs", "B.Sc (PCM)", "BBA", "BCA", "BCA Evening Programs",
    "MBA", "MCA", "M.Com",
]

# Keyword -> course mapping for DSI (order matters: more specific first)
DSI_CAMPAIGN_KEYWORDS = [
    # Engineering specific (before rollup)
    ("medical", "Medical Electronics Engineering"),
    ("ece", "Electronics and Communications Engineering"),
    ("telecom", "Electronics and Communications Engineering"),
    ("electronicsandcommunication", "Electronics and Communications Engineering"),
    ("eee", "Electrical and Electronics Engineering"),
    ("electrical", "Electrical and Electronics Engineering"),
    ("info", "Information Science"),
    ("ise", "Information Science"),
    ("automobile", "Automotive Engineering"),
    ("automotive", "Automotive Engineering"),
    ("mech", "Mechanical Engineering"),
    ("cse", "Computer Science"),
    ("computer", "Computer Science"),
    ("civil", "Civil Engineering"),
    ("chemical", "Chemical Engineering"),
    ("biotech", "Biotechnology"),
    # Architecture
    ("arch", "B. Arch"),
    ("march", "M.Arch"),
    # Degree courses
    ("bcaeve", "BCA Evening"),
    ("bcaevening", "BCA Evening"),
    ("bca", "BCA"),
    ("bcomeve", "B.Com Evening"),
    ("bcom", "B.Com"),
    ("b.com", "B.Com"),
    ("bba", "BBA"),
    ("mba", "MBA"),
    ("mca", "MCA"),
    ("mcom", "M.Com"),
    ("m.com", "M.Com"),
    ("bsc(pcm)", "B.Sc (PCM)"),
    ("pcm", "B.Sc (PCM)"),
    ("bsc", "B.Sc"),
    # Department-level fallbacks
    ("dscasc", "DSCASC - UG"),
    ("dscads", "DSCA"),
    ("dscds", "DSCA"),
    ("dsat", "DSCA"),
    ("dsca", "DSCA"),
    ("dsce", "DSCE"),
    ("engg", "DSCE"),
    ("dsit", "DSIT"),
    ("diploma", "DSIT"),
]

# DSI Source -> course mapping for LeadSquared Student Source
DSI_SOURCE_TO_COURSE = {
    "GGL-BTech": "DSIT",
    "GGL-MBA": "MBA",
    "GGL-BCA": "BCA",
    "GGL-Law": "DSIT",
    "GGL_BBA": "BBA",
    "GGL-DSAT": "DSCA",
    "GGL-B.Pharm": "DSCE",
    "GGL-B.Design": "DSCA",
    "GGL-JMC": "DSCASC - UG",
    "GGL-MCA": "MCA",
    "GGL_B.Com": "B.Com",
}

# DSI fallback department mapping
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

# DSI course normalization
DSI_COURSE_NORMALISE = {
    "b.com": "B.Com",
    "bcom": "B.Com",
    "b.com evening": "B.Com Evening",
    "b.sc(pcm)": "B.Sc (PCM)",
    "b.sc (pcm)": "B.Sc (PCM)",
    "b. arch": "B. Arch",
    "b.arch": "B. Arch",
    "eee": "Electrical and Electronics Engineering",
    "ece": "Electronics and Communications Engineering",
    "cse": "Computer Science",
    "ise": "Information Science",
}


def _map_dsi_campaign_to_course(name: str) -> Optional[str]:
    """Map a DSI campaign name to a course using keyword matching."""
    low = name.lower().strip()
    if not low:
        return None

    # Check exact source mapping first
    if name in DSI_SOURCE_TO_COURSE:
        return DSI_SOURCE_TO_COURSE[name]

    # Remove 'search' for arch detection
    c_no_search = low.replace("search", "")

    for kw, course in DSI_CAMPAIGN_KEYWORDS:
        if kw in low:
            return course

    # Check arch after removing 'search'
    if "arch" in c_no_search:
        return "B. Arch"

    return None


def _get_dsi_dept(course: str) -> str:
    """Get the department for a DSI course name."""
    if not course:
        return ""
    low = course.lower().strip()
    if low in DSI_FALLBACK_DEPT:
        return DSI_FALLBACK_DEPT[low]
    return ""


def _rollup_to_dept(course: str) -> str:
    """For DSI, if course maps to DSCE or DSIT department, return the department name."""
    dept = _get_dsi_dept(course)
    if dept in ("DSCE", "DSIT"):
        return dept
    return course


def _get_dsi_account_creds() -> Dict[str, Any]:
    """Load DSI's Google Ads credentials from the DB."""
    c = sqlite3.connect("adoptima.db")
    cur = c.cursor()
    cur.execute("SELECT google_credentials FROM accounts WHERE name='DSI'")
    row = cur.fetchone()
    c.close()
    if not row or not row[0]:
        raise ValueError("DSI has no stored google_credentials")
    return json.loads(decrypt(row[0]))


def _apply_gst(raw_cost: float, date_str: str) -> float:
    """Apply GST rule: no GST till 18-Jun-2026 inclusive, 18% from 19-Jun-2026 onwards."""
    if not raw_cost or raw_cost <= 0:
        return 0.0
    if not date_str:
        return raw_cost
    try:
        spend_day = date.fromisoformat(date_str[:10])
        cutoff = date(2026, 6, 18)
        if spend_day <= cutoff:
            return raw_cost
        return raw_cost * GST_MULTIPLIER
    except (ValueError, TypeError):
        return raw_cost


# ============================================================================
# Google Ads spend fetch
# ============================================================================

def _fetch_dsi_google_ads_spend(start_date: str, end_date: str) -> Dict[str, float]:
    """Fetch campaign-level spend from Google Ads for DSI, mapped to courses with dept rollup.
    Returns {course: spend_float}."""
    creds = _get_dsi_account_creds()
    from google.ads.googleads.client import GoogleAdsClient

    client_dict = {
        "developer_token": creds["developer_token"],
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "use_proto_plus": True,
    }
    if creds.get("login_customer_id"):
        client_dict["login_customer_id"] = str(creds["login_customer_id"]).replace("-", "")

    gclient = GoogleAdsClient.load_from_dict(client_dict)
    service = gclient.get_service("GoogleAdsService")
    customer_id = DSI_CUSTOMER_ID

    query = f"""
        SELECT
          campaign.id,
          campaign.name,
          segments.date,
          metrics.cost_micros
        FROM campaign
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
    """
    response = service.search(customer_id=customer_id, query=query)

    course_spend = defaultdict(float)
    for row in response:
        cost = (row.metrics.cost_micros or 0) / 1_000_000.0
        if cost == 0:
            continue
        day_str = str(row.segments.date) if row.segments.date else ""
        cost_with_gst = _apply_gst(cost, day_str)
        campaign_name = row.campaign.name
        course = _map_dsi_campaign_to_course(campaign_name)
        if course:
            rolled_up = _rollup_to_dept(course)
            course_spend[rolled_up] += cost_with_gst
        else:
            # Try keyword-based fallback on the campaign name
            course_spend[campaign_name] += cost_with_gst

    return dict(course_spend)


def _fetch_dsi_google_ads_spend_daily(start_date: str, end_date: str) -> Dict[str, Dict[str, float]]:
    """Fetch campaign-level spend from Google Ads for DSI grouped by date.
    Returns {date_str: {course: spend_float}}."""
    creds = _get_dsi_account_creds()
    from google.ads.googleads.client import GoogleAdsClient

    client_dict = {
        "developer_token": creds["developer_token"],
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "use_proto_plus": True,
    }
    if creds.get("login_customer_id"):
        client_dict["login_customer_id"] = str(creds["login_customer_id"]).replace("-", "")

    gclient = GoogleAdsClient.load_from_dict(client_dict)
    service = gclient.get_service("GoogleAdsService")
    customer_id = DSI_CUSTOMER_ID

    query = f"""
        SELECT
          campaign.id,
          campaign.name,
          segments.date,
          metrics.cost_micros
        FROM campaign
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
    """
    response = service.search(customer_id=customer_id, query=query)

    daily_spend = defaultdict(lambda: defaultdict(float))
    for row in response:
        cost = (row.metrics.cost_micros or 0) / 1_000_000.0
        if cost == 0:
            continue
        day_str = str(row.segments.date) if row.segments.date else ""
        cost_with_gst = _apply_gst(cost, day_str)
        campaign_name = row.campaign.name
        course = _map_dsi_campaign_to_course(campaign_name)
        if course:
            rolled_up = _rollup_to_dept(course)
            daily_spend[day_str][rolled_up] += cost_with_gst
        else:
            daily_spend[day_str][campaign_name] += cost_with_gst

    return {k: dict(v) for k, v in daily_spend.items()}


def _fetch_dsi_google_ads_monthly_spend(start_date: str, end_date: str) -> Dict[str, float]:
    """Fetch Google Ads spend for DSI grouped by month.
    Returns {month_key: spend_float} where month_key is 'MMM-YYYY'."""
    creds = _get_dsi_account_creds()
    from google.ads.googleads.client import GoogleAdsClient
    from collections import defaultdict as dd

    client_dict = {
        "developer_token": creds["developer_token"],
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "use_proto_plus": True,
    }
    if creds.get("login_customer_id"):
        client_dict["login_customer_id"] = str(creds["login_customer_id"]).replace("-", "")

    gclient = GoogleAdsClient.load_from_dict(client_dict)
    service = gclient.get_service("GoogleAdsService")
    customer_id = DSI_CUSTOMER_ID

    query = f"""
        SELECT
          campaign.id,
          campaign.name,
          segments.month,
          metrics.cost_micros
        FROM campaign
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
    """
    response = service.search(customer_id=customer_id, query=query)

    month_spend = dd(float)
    months_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    for row in response:
        cost = (row.metrics.cost_micros or 0) / 1_000_000.0
        if cost == 0:
            continue
        month_str = str(row.segments.month) if row.segments.month else ""
        if not month_str:
            continue
        # Normalize month key
        try:
            d = date.fromisoformat(month_str)
            mk = f"{months_order[d.month - 1]}-{d.year}"
        except (ValueError, TypeError):
            mk = month_str

        # Apply GST: months after Jun-2026 get 18%
        try:
            parts = mk.split("-")
            year = int(parts[1])
            m_idx = months_order.index(parts[0]) if parts[0] in months_order else 0
            if year > 2026 or (year == 2026 and m_idx > 5):
                cost = cost * GST_MULTIPLIER
        except (ValueError, IndexError):
            pass

        month_spend[mk] += cost

    return dict(month_spend)


# ============================================================================
# LeadSquared lead fetch with full details
# ============================================================================

def _fetch_dsi_lsq_leads(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """Fetch full lead details from LeadSquared for DSI.
    Returns list of lead dicts with source, stage, application_status, course, department."""
    import requests
    from backend.services.config import load_config

    access_key = ""
    secret_key = ""
    base_url = ""

    c = sqlite3.connect("adoptima.db")
    cur = c.cursor()
    cur.execute("SELECT lsq_access_key, lsq_secret_key, lsq_base_url FROM accounts WHERE id=?", (DSI_ACCOUNT_ID,))
    row = cur.fetchone()
    c.close()
    if row and row[0] and row[1]:
        access_key = row[0]
        secret_key = row[1]
        base_url = row[2] or ""

    if not access_key:
        cfg = load_config()
        access_key = cfg.get("leadsquared_access_key", "")
        secret_key = cfg.get("leadsquared_secret_key", "")
        base_url = cfg.get("leadsquared_base_url", "")

    if not base_url or not access_key or not secret_key:
        logger.warning("LeadSquared credentials not configured for DSI; returning empty list.")
        return []

    base_url = base_url.rstrip("/")
    if not base_url.endswith("/v2"):
        base_url = base_url + "/v2"

    today_str = (date.today() + timedelta(days=1)).isoformat()
    url = f"{base_url}/LeadManagement.svc/Leads.RecentlyModified"

    all_leads = []
    page = 1
    max_pages = 100
    total_records = None

    while page <= max_pages:
        payload = {
            "Parameter": {
                "FromDate": f"{start_date} 00:00:00",
                "ToDate": f"{today_str} 23:59:59",
            },
            "Columns": {
                "Include_CSV": "ProspectID,Source,SourceCampaign,CreatedOn,mx_Student_Source,mx_Student_Stage,mx_Application_Status,mx_Latest_Source,mx_Secondary_Source,mx_Application_Course,mx_Course_DSIT_Diploma,mx_DSCA_Course,mx_DSCASC_Course,mx_DSCE_Course"
            },
            "Paging": {"PageIndex": page, "PageSize": 1000},
            "Sorting": {"ColumnName": "ProspectAutoId", "Direction": "1"},
        }
        success = False
        import time as time_module
        for attempt in range(3):
            try:
                r = requests.post(url, params={"accessKey": access_key, "secretKey": secret_key}, json=payload, timeout=120)
                r.raise_for_status()
                resp = r.json()
                success = True
                break
            except Exception as e:
                logger.warning(f"DSI LSQ page {page} attempt {attempt+1} failed: {e}")
                time_module.sleep(5)
        if not success:
            logger.error(f"DSI LSQ page {page} failed after 3 retries, stopping")
            break

        if total_records is None:
            total_records = resp.get("RecordCount", 0)
            logger.info(f"DSI LSQ total modified leads: {total_records}")
        records = resp.get("Leads", [])
        if not records:
            break

        for rec in records:
            props = {}
            for item in rec.get("LeadPropertyList", []):
                props[item.get("Attribute", "")] = item.get("Value", "")
            created = (props.get("CreatedOn") or "")
            source = (props.get("Source") or "")
            created_day = created[:10]
            if not (start_date <= created_day <= end_date):
                continue

            student_source = (props.get("mx_Student_Source") or "")
            latest_source = (props.get("mx_Latest_Source") or "")
            secondary_source = (props.get("mx_Secondary_Source") or "")
            source_combined = " ".join([source, student_source, latest_source, secondary_source]).upper()
            if "GGL" not in source_combined and "PROGRAMMATIC" not in source_combined:
                continue

            stage = (props.get("mx_Student_Stage") or "")
            application_status = (props.get("mx_Application_Status") or "")

            # DSI: check 5 course columns in priority order
            app_course = (props.get("mx_Application_Course") or "").strip()
            dsit_diploma = (props.get("mx_Course_DSIT_Diploma") or "").strip()
            dsca_course = (props.get("mx_DSCA_Course") or "").strip()
            dscasc_course = (props.get("mx_DSCASC_Course") or "").strip()
            dsce_course = (props.get("mx_DSCE_Course") or "").strip()

            # Priority: DSCA > DSCASC > DSIT > DSCE > Application
            raw_course = ""
            for val in [dsca_course, dscasc_course, dsit_diploma, dsce_course, app_course]:
                if val and val != "--":
                    raw_course = val
                    break

            # If no course column, try mapping from source
            if not raw_course:
                mapped = _map_dsi_campaign_to_course(source)
                raw_course = mapped or source

            # Apply normalization
            low_course = raw_course.lower().strip()
            if low_course in DSI_COURSE_NORMALISE:
                raw_course = DSI_COURSE_NORMALISE[low_course]

            # Department rollup
            clean_course = _rollup_to_dept(raw_course)
            department = _get_dsi_dept(clean_course) or _get_dsi_dept(raw_course)

            all_leads.append({
                "source": source,
                "student_source": student_source,
                "stage": stage,
                "application_status": application_status,
                "created_on": created_day,
                "course": clean_course,
                "department": department,
                "raw_course": raw_course,
            })

        if len(records) < 1000:
            break
        page += 1

    logger.info(f"DSI LSQ fetch complete: {len(all_leads)} GGL/Programmatic leads for {start_date} to {end_date}")
    return all_leads


# ============================================================================
# Table 1 & 2: Daily and Cumulative Campaign Metrics
# ============================================================================

def _dept_sort_key(course):
    """Sort key for DSI courses using DEPT_ORDER."""
    low = course.lower().strip()
    return (DEPT_ORDER.get(low, 99), course)


def fetch_dsi_daily_range(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """Fetch DSI course performance for a date range (Table 1).
    Returns list of {department, course, leads, cpl, spend} sorted by dept order."""
    spend_data = _fetch_dsi_google_ads_spend(start_date, end_date)
    leads = _fetch_dsi_lsq_leads(start_date, end_date)

    leads_by_course = defaultdict(int)
    for lead in leads:
        leads_by_course[lead["course"]] += 1

    all_courses = set(spend_data.keys()) | set(leads_by_course.keys())
    rows = []
    for course in all_courses:
        spend = round(spend_data.get(course, 0))
        leads_count = leads_by_course.get(course, 0)
        cpl = round(spend / leads_count) if leads_count else None
        dept = _get_dsi_dept(course)
        if spend > 0 or leads_count > 0:
            rows.append({
                "department": dept,
                "course": course,
                "leads": leads_count,
                "cpl": cpl,
                "spend": spend,
            })

    rows.sort(key=lambda r: _dept_sort_key(r["course"]))
    return rows


def fetch_dsi_cumulative_range(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """Fetch DSI cumulative course performance for a date range (Table 2).
    Returns list of {department, course, leads, cpl, spend} sorted by dept order."""
    return fetch_dsi_daily_range(start_date, end_date)


# ============================================================================
# Table 3: Lead Attribution Pivot (Course × Stage)
# ============================================================================

def fetch_dsi_lead_pivot(start_date: str, end_date: str) -> Dict[str, Any]:
    """Fetch DSI lead attribution pivot: Course × Student Stage (Table 3).
    Rows are by course (with department rollup), columns by stage."""
    leads = _fetch_dsi_lsq_leads(start_date, end_date)

    matrix_map = defaultdict(lambda: defaultdict(int))
    unique_stages = set()

    for lead in leads:
        course = lead["course"]
        stage = lead["stage"]
        if course and stage:
            matrix_map[course][stage] += 1
            unique_stages.add(stage)

    all_stages = sorted(unique_stages)

    rows = []
    for course in sorted(matrix_map.keys(), key=lambda c: _dept_sort_key(c)):
        row = {"course": course}
        for stage in all_stages:
            row[stage] = matrix_map[course].get(stage, 0)
        rows.append(row)

    column_totals = {}
    grand_total = 0
    for stage in all_stages:
        col_sum = sum(matrix_map[course].get(stage, 0) for course in matrix_map)
        column_totals[stage] = col_sum
        grand_total += col_sum

    return {
        "stages": all_stages,
        "rows": rows,
        "column_totals": column_totals,
        "grand_total": grand_total,
    }


# ============================================================================
# Table 4: Application MIS (Application Submitted & CPA by Department)
# ============================================================================

APPLICATION_SUBMITTED_STATUSES = {
    "application fee paid",
    "application submitted",
    "enrolled",
    "partially paid",
}

# DSI Table 4 sections
DSI_T4_SECTIONS = [
    {"label": "DSCE", "courses": [{"key": "DSCE", "display": "DSCE", "target": 0}]},
    {"label": "DSIT", "courses": [{"key": "DSIT", "display": "DSIT", "target": 0}]},
    {"label": "DSCA", "courses": [
        {"key": "Arch", "display": "Arch", "target": 0},
        {"key": "Bachelor of Architecture Campus 1", "display": "B. Arch", "target": 0},
        {"key": "M.Arch", "display": "M.Arch", "target": 0},
    ]},
    {"label": "DSCASC - UG", "courses": [
        {"key": "B.Com", "display": "B.Com", "target": 0},
        {"key": "B.Com Evening Programs", "display": "B.Com Evening", "target": 0},
        {"key": "B.Sc (PCM)", "display": "B.Sc (PCM)", "target": 0},
        {"key": "BBA", "display": "BBA", "target": 0},
        {"key": "BCA", "display": "BCA", "target": 0},
        {"key": "BCA Evening Programs", "display": "BCA Evening", "target": 0},
    ]},
    {"label": "DSCASC - Masters", "courses": [
        {"key": "MBA", "display": "MBA", "target": 0},
        {"key": "MCA", "display": "MCA", "target": 0},
        {"key": "M.Com", "display": "M.Com", "target": 0},
    ]},
]


def fetch_dsi_application_mis(start_date: str, end_date: str) -> Dict[str, Any]:
    """Fetch DSI Application MIS (Table 4).
    Returns sections with rows, section totals, and grand total."""
    leads = _fetch_dsi_lsq_leads(start_date, end_date)

    submitted_counts = defaultdict(int)
    for lead in leads:
        status_lower = (lead["application_status"] or "").lower().strip()
        if status_lower in APPLICATION_SUBMITTED_STATUSES:
            course = lead["course"]
            submitted_counts[course] += 1

    spend_data = _fetch_dsi_google_ads_spend(start_date, end_date)

    sections = []
    grand_submitted = 0
    grand_spend = 0
    grand_target = 0

    for section in DSI_T4_SECTIONS:
        section_rows = []
        sec_submitted = 0
        sec_spend = 0
        sec_target = 0

        for c in section["courses"]:
            submitted = submitted_counts.get(c["key"], 0)
            spend = round(spend_data.get(c["key"], 0))
            cpa = round(spend / submitted) if submitted > 0 else 0
            section_rows.append({
                "course": c["display"],
                "submitted": submitted,
                "spend": spend,
                "cpa": cpa,
                "target": c["target"],
            })
            sec_submitted += submitted
            sec_spend += spend
            sec_target += c["target"]

        sec_cpa = round(sec_spend / sec_submitted) if sec_submitted > 0 else 0
        section_total = {
            "course": "Total",
            "submitted": sec_submitted,
            "spend": sec_spend,
            "cpa": sec_cpa,
            "target": sec_target,
        }

        sections.append({
            "label": section["label"],
            "rows": section_rows,
            "total": section_total,
        })

        grand_submitted += sec_submitted
        grand_spend += sec_spend
        grand_target += sec_target

    grand_cpa = round(grand_spend / grand_submitted) if grand_submitted > 0 else 0
    grand_total = {
        "course": "GRAND TOTAL",
        "submitted": grand_submitted,
        "spend": grand_spend,
        "cpa": grand_cpa,
        "target": grand_target,
    }

    return {
        "sections": sections,
        "grand_total": grand_total,
    }


# ============================================================================
# Table 5: Budget MIS by Department
# ============================================================================

DSI_T5_SECTIONS = [
    {"label": "DSCE", "courses": [{"key": "DSCE", "display": "DSCE"}]},
    {"label": "DSIT", "courses": [{"key": "DSIT", "display": "DSIT"}]},
    {"label": "DSCA", "courses": [
        {"key": "Arch", "display": "Arch"},
        {"key": "Bachelor of Architecture Campus 1", "display": "B. Arch"},
        {"key": "M.Arch", "display": "M.Arch"},
    ]},
    {"label": "DSCASC - UG", "courses": [
        {"key": "B.Com", "display": "B.Com"},
        {"key": "B.Com Evening Programs", "display": "B.Com Evening"},
        {"key": "B.Sc (PCM)", "display": "B.Sc (PCM)"},
        {"key": "BBA", "display": "BBA"},
        {"key": "BCA", "display": "BCA"},
        {"key": "BCA Evening Programs", "display": "BCA Evening"},
    ]},
    {"label": "DSCASC - Masters", "courses": [
        {"key": "MBA", "display": "MBA"},
        {"key": "MCA", "display": "MCA"},
        {"key": "M.Com", "display": "M.Com"},
    ]},
]


def fetch_dsi_budget_mis(start_date: str, end_date: str, db_session=None) -> Dict[str, Any]:
    """Fetch DSI Budget MIS (Table 5).
    Uses Google Ads for spend + dsi_budget_entries for budget amounts."""
    spend_data = _fetch_dsi_google_ads_spend(start_date, end_date)

    # Fetch budgets from DB
    section_budgets = defaultdict(float)
    if db_session:
        from backend.db.models import DsiBudgetEntry
        entries = db_session.query(DsiBudgetEntry).all()
        for entry in entries:
            if entry.section:
                section_budgets[entry.section] += entry.amount

    sections = []
    grand_budget = 0.0
    grand_spend = 0.0

    for section in DSI_T5_SECTIONS:
        section_rows = []
        sec_spend = 0

        for c in section["courses"]:
            spend = round(spend_data.get(c["key"], 0))
            status = "Live" if spend > 0 else "Paused"
            section_rows.append({
                "course": c["display"],
                "status": status,
                "spend": spend,
            })
            sec_spend += spend

        sec_budget = section_budgets.get(section["label"], 0.0)
        sec_remaining = sec_budget - sec_spend

        sections.append({
            "label": section["label"],
            "rows": section_rows,
            "total": {
                "course": "Total",
                "budget": round(sec_budget),
                "spend": sec_spend,
                "remaining": round(sec_remaining),
            },
        })

        grand_budget += sec_budget
        grand_spend += sec_spend

    grand_total = {
        "course": "GRAND TOTAL",
        "budget": round(grand_budget),
        "spend": grand_spend,
        "remaining": round(grand_budget - grand_spend),
    }

    return {
        "sections": sections,
        "grand_total": grand_total,
    }