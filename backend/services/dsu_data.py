"""
Live data fetcher for DSU course performance report.
Pulls campaign spend from Google Ads API and leads from LeadSquared.
Maps both to the DSU course taxonomy.
"""
import json
import sqlite3
import logging
from datetime import date, timedelta
from collections import defaultdict
from typing import Dict, Any, List, Optional

from backend.services.crypto import decrypt

logger = logging.getLogger("AdOptima")

# Cache for LSQ lead counts (keyed by "start_date_end_date")
_LSQ_CACHE: Dict[str, Dict[str, int]] = {}
_LSQ_CACHE_TIME: Dict[str, float] = {}
_LSQ_CACHE_TTL = 1800  # 30 minutes in seconds

# Course list as shown in DSU Table 1
DSU_COURSES = [
    "B.Tech", "MBA", "B.Sc Cyber Security", "School of Law", "BCA", "BBA",
    "B.Sc Biological Sciences", "M.Sc Data Science", "M.Sc Biological Sciences",
    "B.Sc Data Science", "M.Sc Cyber Security", "MCA", "B.Design", "JMC",
    "B.Pharm", "B.Com", "B.Sc Nursing", "BPT", "M.Tech", "DSAT",
]

# Keyword -> course mapping (order matters: more specific first)
CAMPAIGN_KEYWORDS = [
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
    ("pmax_btech", "B.Tech"),
    ("iit jee", "B.Tech"),
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
    ("dsat", "DSAT"),
]

# Student Source -> course mapping for LeadSquared
SOURCE_TO_COURSE = {
    "GGL-BTech": "B.Tech",
    "GGL-MBA": "MBA",
    "GGL-BCA": "BCA",
    "GGL-Law": "School of Law",
    "GGL_BBA": "BBA",
    "GGL_Biological_Science_BSc": "B.Sc Biological Sciences",
    "GGL_Biological_Science_MSc": "M.Sc Biological Sciences",
    "GGL_Cyber_Security_BSc": "B.Sc Cyber Security",
    "GGL_Cyber_Security_MSc": "M.Sc Cyber Security",
    "GGL_Data_Science_MSc": "M.Sc Data Science",
    "GGL_Data_Science_BSc": "B.Sc Data Science",
    "GGL-DSAT": "DSAT",
    "GGL-B.Pharm": "B.Pharm",
    "GGL-B.Design": "B.Design",
    "GGL-JMC": "JMC",
    "GGL-MCA": "MCA",
    "GGL_B.Com": "B.Com",
    "GGL-MSC.Biological.Science": "M.Sc Biological Sciences",
}


def _map_campaign_to_course(name: str) -> Optional[str]:
    low = name.lower()
    for kw, course in CAMPAIGN_KEYWORDS:
        if kw in low:
            return course
    return None


def _get_dsu_account_creds() -> Dict[str, Any]:
    """Load DSU's Google Ads credentials from the DB."""
    c = sqlite3.connect("adoptima.db")
    cur = c.cursor()
    cur.execute("SELECT google_credentials FROM accounts WHERE name='DSU'")
    row = cur.fetchone()
    c.close()
    if not row or not row[0]:
        raise ValueError("DSU has no stored google_credentials")
    return json.loads(decrypt(row[0]))


def _fetch_google_ads_spend(start_date: str, end_date: str) -> Dict[str, float]:
    """Fetch campaign-level spend from Google Ads, mapped to courses.
    Returns {course: spend_float}."""
    creds = _get_dsu_account_creds()
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
    customer_id = "2909919094"  # DSU customer ID

    query = f"""
        SELECT
          campaign.id,
          campaign.name,
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
        course = _map_campaign_to_course(row.campaign.name)
        if course:
            course_spend[course] += cost
    return dict(course_spend)


def _fetch_lsq_leads(start_date: str, end_date: str, account_id: int = None) -> Dict[str, int]:
    """Fetch leads from LeadSquared, mapped to courses.
    Filters: CreatedOn within date range AND Source contains "GGL" or "Programmatic".
    Uses per-account LSQ credentials if account_id is provided, else falls back to global config.
    Results are cached per date range to avoid repeated slow API calls.
    Returns {course: lead_count}."""
    cache_key = f"{account_id}_{start_date}_{end_date}"
    import time
    if cache_key in _LSQ_CACHE and (time.time() - _LSQ_CACHE_TIME.get(cache_key, 0)) < _LSQ_CACHE_TTL:
        logger.info(f"LSQ leads cache hit for {cache_key}")
        return _LSQ_CACHE[cache_key]

    import requests
    import sqlite3
    from backend.services.config import load_config

    access_key = ""
    secret_key = ""
    base_url = ""

    # Try per-account credentials first
    if account_id:
        c = sqlite3.connect("adoptima.db")
        cur = c.cursor()
        cur.execute("SELECT lsq_access_key, lsq_secret_key, lsq_base_url FROM accounts WHERE id=?", (account_id,))
        row = cur.fetchone()
        c.close()
        if row and row[0] and row[1]:
            access_key = row[0]
            secret_key = row[1]
            base_url = row[2] or ""
            logger.info(f"Using per-account LSQ creds for account_id={account_id}")

    # Fall back to global config
    if not access_key:
        cfg = load_config()
        access_key = cfg.get("leadsquared_access_key", "")
        secret_key = cfg.get("leadsquared_secret_key", "")
        base_url = cfg.get("leadsquared_base_url", "")
        logger.info(f"Using global LSQ creds for account_id={account_id}")

    if not base_url or not access_key or not secret_key:
        logger.warning(f"LeadSquared credentials not configured for account_id={account_id}; leads will be 0.")
        return {}
    base_url = base_url.rstrip("/")
    if not base_url.endswith("/v2"):
        base_url = base_url + "/v2"

    url = f"{base_url}/LeadManagement.svc/Leads.RecentlyModified"
    course_leads = defaultdict(int)
    page = 1
    max_pages = 50
    total_records = None
    total_fetched = 0

    while page <= max_pages:
        payload = {
            "Parameter": {
                "FromDate": f"{start_date} 00:00:00",
                "ToDate": f"{end_date} 23:59:59",
            },
            "Columns": {
                "Include_CSV": "ProspectID,Source,SourceCampaign,CreatedOn"
            },
            "Paging": {"PageIndex": page, "PageSize": 1000},
            "Sorting": {"ColumnName": "ProspectAutoId", "Direction": "1"},
        }
        success = False
        for attempt in range(3):
            try:
                r = requests.post(url, params={"accessKey": access_key, "secretKey": secret_key}, json=payload, timeout=120)
                r.raise_for_status()
                resp = r.json()
                success = True
                break
            except Exception as e:
                logger.warning(f"LeadSquared page {page} attempt {attempt+1} failed: {e}")
                time.sleep(5)
        if not success:
            logger.error(f"LeadSquared page {page} failed after 3 retries, stopping")
            break

        if total_records is None:
            total_records = resp.get("RecordCount", 0)
            logger.info(f"LSQ total leads for {start_date} to {end_date}: {total_records}")
        records = resp.get("Leads", [])
        if not records:
            break

        for rec in records:
            props = {}
            for item in rec.get("LeadPropertyList", []):
                props[item.get("Attribute", "")] = item.get("Value", "")
            created = (props.get("CreatedOn") or "")
            source = (props.get("Source") or "")
            source_upper = source.upper()

            # Filter 1: CreatedOn must be within the date range
            created_day = created[:10]
            if not (start_date <= created_day <= end_date):
                continue

            # Filter 2: Source must contain "GGL" or "Programmatic"
            if "GGL" not in source_upper and "PROGRAMMATIC" not in source_upper:
                continue

            course = _map_campaign_to_course(source)
            if course:
                course_leads[course] += 1
            else:
                # Count unmapped sources under their own source name
                course_leads[source] += 1

        total_fetched += len(records)
        logger.info(f"LSQ page {page}: fetched {len(records)} (total: {total_fetched}/{total_records}), ggl/prog leads: {sum(course_leads.values())}")
        if len(records) < 1000:
            break
        page += 1

    result = dict(course_leads)
    _LSQ_CACHE[cache_key] = result
    _LSQ_CACHE_TIME[cache_key] = time.time()
    logger.info(f"LSQ leads cached for {cache_key}: {sum(result.values())} total GGL/Programmatic leads across {len(result)} courses")
    return result


def fetch_dsu_daily(report_date: str) -> List[Dict[str, Any]]:
    """Fetch daily course performance for a given date.
    Returns list of {course, leads, cpl, spend} sorted by spend desc."""
    spend_data = _fetch_google_ads_spend(report_date, report_date)
    lead_data = _fetch_lsq_leads(report_date, report_date, account_id=1)

    rows = []
    for course in DSU_COURSES:
        spend = round(spend_data.get(course, 0))
        leads = lead_data.get(course, 0)
        cpl = round(spend / leads) if leads else None
        rows.append({"course": course, "leads": leads, "cpl": cpl, "spend": spend})

    rows.sort(key=lambda r: -r["spend"])
    return rows


def fetch_dsu_cumulative(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """Fetch cumulative course performance from start_date to end_date.
    Returns list of {course, leads, cpl, spend} sorted by spend desc."""
    spend_data = _fetch_google_ads_spend(start_date, end_date)
    lead_data = _fetch_lsq_leads(start_date, end_date, account_id=1)

    rows = []
    # Include all courses that have either spend or leads
    all_courses = set(DSU_COURSES) | set(spend_data.keys()) | set(lead_data.keys())
    for course in all_courses:
        spend = round(spend_data.get(course, 0))
        leads = lead_data.get(course, 0)
        cpl = round(spend / leads) if leads else None
        if spend > 0 or leads > 0:
            rows.append({"course": course, "leads": leads, "cpl": cpl, "spend": spend})

    rows.sort(key=lambda r: -r["spend"])
    return rows