"""
LeadSquared lead mirror service.

Maintains a local SQLite copy of LeadSquared leads so InsightDesk reports load
in milliseconds instead of waiting for the slow Leads.RecentlyModified API.

Strategy:
- Full sync uses Leads.Get with source-field searches (Source / Student Source /
  Latest Source / Secondary Source LIKE 'GGL%' or 'Programmatic%'). This avoids
  scanning millions of RecentlyModified records.
- Incremental sync uses Leads.Get with CreatedOn >= last synced date and then
  filters GGL/Programmatic locally.
- A scheduler job refreshes DSU and DSI mirrors every 3 hours.
- Report fetchers query the local `leadsquared_leads` table by CreatedOn date.
"""
import json
import logging
import time as time_module
from datetime import date, timedelta
from typing import Dict, Any, List, Optional, Set

import requests
from sqlalchemy.orm import Session

from backend.db.database import SessionLocal
from backend.db.models import Account, LeadSquaredLead
from backend.services.config import load_config
from backend.services.dsu_data import SOURCE_TO_COURSE, _map_campaign_to_course

logger = logging.getLogger("AdOptima")


# Searchable fields for the local mirror. LeadSquared's Leads.Get can only
# reliably search the built-in Source field; custom-field date filtered
# searches intermittently return 500 errors. We therefore search Source for
# GGL and Programmatic and mirror those leads. Student Source is still stored
# in the mirror for traceability and post-filtered by _is_ggl_or_programmatic.
_SOURCE_FIELDS = [
    ("Source", False),
]


def _resolve_dsi_course(raw_course: str) -> str:
    """Normalize and roll up a DSI course value to a department/course label."""
    from backend.services.dsi_data import (
        DSI_COURSE_NORMALISE,
        _rollup_to_dept,
    )
    low = (raw_course or "").lower().strip()
    if low in DSI_COURSE_NORMALISE:
        raw_course = DSI_COURSE_NORMALISE[low]
    clean = _rollup_to_dept(raw_course)
    return clean or raw_course


def _resolve_course(source: str) -> Optional[str]:
    """Resolve a LeadSquared source string to a DSU/DSI course name."""
    if not source:
        return None
    s = source.strip()
    course = SOURCE_TO_COURSE.get(s)
    if course:
        return course
    return _map_campaign_to_course(s)


def _get_lsq_credentials(account: Account) -> tuple:
    """Return (access_key, secret_key, base_url) for an account, with global fallback."""
    access_key = (account.lsq_access_key or "").strip()
    secret_key = (account.lsq_secret_key or "").strip()
    base_url = (account.lsq_base_url or "").strip()

    if not access_key or not secret_key:
        cfg = load_config()
        access_key = cfg.get("leadsquared_access_key", "")
        secret_key = cfg.get("leadsquared_secret_key", "")
        base_url = cfg.get("leadsquared_base_url", "")

    if base_url:
        base_url = base_url.rstrip("/")
        if not base_url.endswith("/v2"):
            base_url = base_url + "/v2"

    return access_key, secret_key, base_url


def _parse_lsq_record(rec: Dict[str, Any], include_dsi_course_columns: bool = False) -> Dict[str, Any]:
    """Flatten a LeadSquared lead record into a dictionary.

    Handles both formats:
      - Leads.RecentlyModified returns {"LeadPropertyList": [{"Attribute": ..., "Value": ...}]}
      - Leads.Get returns a flat dict with keys like ProspectID, Source, CreatedOn, etc.
    """
    props = {}
    if isinstance(rec, dict):
        # Leads.Get returns flat keys directly
        for key in rec:
            if key not in ("Fields", "ProspectAutoId", "OwnerId"):
                props[key] = rec[key]
        # Leads.RecentlyModified returns LeadPropertyList
        for item in rec.get("LeadPropertyList", []):
            attr = item.get("Attribute", "")
            if attr:
                props[attr] = item.get("Value", "")

    created = (props.get("CreatedOn") or "")[:10]
    modified = (props.get("ModifiedOn") or props.get("LastModifiedOn") or "")[:10]
    source = props.get("Source", "")

    # Resolve course. For DSI we also inspect the course-specific columns.
    course = _resolve_course(source)
    if include_dsi_course_columns:
        app_course = (props.get("mx_Application_Course") or "").strip()
        dsit_diploma = (props.get("mx_Course_DSIT_Diploma") or "").strip()
        dsca_course = (props.get("mx_DSCA_Course") or "").strip()
        dscasc_course = (props.get("mx_DSCASC_Course") or "").strip()
        dsce_course = (props.get("mx_DSCE_Course") or "").strip()
        raw_course = ""
        for val in [dsca_course, dscasc_course, dsit_diploma, dsce_course, app_course]:
            if val and val != "--":
                raw_course = val
                break
        if raw_course:
            course = _resolve_dsi_course(raw_course)
        elif not course:
            course = _resolve_dsi_course(source)

    return {
        "prospect_id": props.get("ProspectID", "") or rec.get("ProspectID", ""),
        "source": source,
        "source_campaign": props.get("SourceCampaign", ""),
        "student_source": props.get("mx_Student_Source", ""),
        "latest_source": props.get("mx_Latest_Source", ""),
        "secondary_source": props.get("mx_Secondary_Source", ""),
        "student_stage": props.get("mx_Student_Stage", ""),
        "application_status": props.get("mx_Application_Status", ""),
        "created_on": created,
        "modified_on": modified,
        "course": course,
        "raw_json": json.dumps(props, ensure_ascii=False),
    }


def _is_ggl_or_programmatic(props_or_record: Dict[str, Any]) -> bool:
    """Check if Source or mx_Student_Source contains GGL or Programmatic.

    We intentionally do NOT use mx_Latest_Source / mx_Secondary_Source as the
    primary count filter, because those fields often reflect later attribution
    changes rather than the original lead source. InsightDesk counts leads by
    their original Source (or Student Source) matching the user's raw data.
    """
    source = (props_or_record.get("source") or "").upper()
    student_source = (props_or_record.get("student_source") or "").upper()
    combined = f"{source} {student_source}"
    return "GGL" in combined or "PROGRAMMATIC" in combined


def _fetch_lsq_get_page(
    base_url: str,
    access_key: str,
    secret_key: str,
    lookup_name: str,
    lookup_value: str,
    operator: str,
    since_date: str,
    page: int,
    page_size: int = 100,
) -> List[Dict[str, Any]]:
    """Fetch one page from LeadSquared Leads.Get with a date + search filter.

    Uses a small page size because the endpoint intermittently returns 500
    errors for large pages or heavy queries.
    """
    url = f"{base_url}/LeadManagement.svc/Leads.Get"
    payload = {
        "Parameter": {
            "LookupName": lookup_name,
            "LookupValue": lookup_value,
            "SqlOperator": operator,
            "LookupName2": "CreatedOn",
            "LookupValue2": f"{since_date} 00:00:00",
            "SqlOperator2": ">=",
            "Logic": "AND",
        },
        "Columns": {
            "Include_CSV": "ProspectID,Source,SourceCampaign,CreatedOn,ModifiedOn,LastModifiedOn,mx_Student_Source,mx_Student_Stage,mx_Application_Status,mx_Latest_Source,mx_Secondary_Source"
        },
        "Paging": {"PageIndex": page, "PageSize": page_size},
        "Sorting": {"ColumnName": "ProspectAutoId", "Direction": "1"},
    }

    for attempt in range(5):
        try:
            r = requests.post(url, params={"accessKey": access_key, "secretKey": secret_key}, json=payload, timeout=120)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                return data
            return data.get("Leads", [])
        except Exception as e:
            logger.warning(f"LeadSquared Leads.Get page {page} attempt {attempt + 1} failed: {e}")
            time_module.sleep(min(2 ** attempt, 30))
    logger.error(f"LeadSquared Leads.Get page {page} failed after 5 retries")
    return []


def _search_lsq_by_source_field(
    base_url: str,
    access_key: str,
    secret_key: str,
    field_name: str,
    search_term: str,
    since_date: str,
    include_dsi_course_columns: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Search Leads.Get for leads where field_name LIKE search_term and CreatedOn >= since_date.

    Returns a dict keyed by ProspectID with parsed record data.
    """
    results: Dict[str, Dict[str, Any]] = {}
    page = 1
    max_pages = 300

    while page <= max_pages:
        records = _fetch_lsq_get_page(
            base_url, access_key, secret_key,
            lookup_name=field_name,
            lookup_value=search_term,
            operator="LIKE",
            since_date=since_date,
            page=page,
        )
        if not records:
            break

        for rec in records:
            parsed = _parse_lsq_record(rec, include_dsi_course_columns=include_dsi_course_columns)
            created = parsed.get("created_on") or ""
            if created and created < since_date:
                continue
            if not _is_ggl_or_programmatic(parsed):
                continue
            prospect_id = parsed["prospect_id"]
            # If duplicate from another search, prefer the one with a resolved course
            existing = results.get(prospect_id)
            if existing and existing.get("course") and not parsed.get("course"):
                continue
            results[prospect_id] = parsed

        logger.info(f"LSQ search {field_name} LIKE '{search_term}' page {page}: {len(records)} records, matched {len(results)}")
        if len(records) < 100:
            break
        page += 1

    return results


def _full_sync_by_source(
    account: Account,
    access_key: str,
    secret_key: str,
    base_url: str,
    since_date: str,
    db: Session,
) -> Dict[str, Any]:
    """Rebuild the mirror by searching each source field for GGL/Programmatic."""
    logger.info(f"LSQ mirror full sync for account {account.id} ({account.name}) since {since_date}")

    include_dsi = account.name == "DSI"
    all_leads: Dict[str, Dict[str, Any]] = {}
    search_terms = ["GGL", "Programmatic"]

    for field_name, _ in _SOURCE_FIELDS:
        for term in search_terms:
            found = _search_lsq_by_source_field(base_url, access_key, secret_key, field_name, term, since_date, include_dsi_course_columns=include_dsi)
            for prospect_id, lead in found.items():
                existing = all_leads.get(prospect_id)
                if existing and existing.get("course") and not lead.get("course"):
                    continue
                all_leads[prospect_id] = lead

    logger.info(f"LSQ mirror full sync: {len(all_leads)} unique GGL/Programmatic leads found")

    # Wipe existing mirror for this account and rebuild
    db.query(LeadSquaredLead).filter(LeadSquaredLead.account_id == account.id).delete(synchronize_session=False)

    for lead in all_leads.values():
        db.add(
            LeadSquaredLead(
                account_id=account.id,
                **lead,
                synced_at=datetime.utcnow(),
            )
        )

    db.commit()
    logger.info(f"LSQ mirror full sync complete: {len(all_leads)} leads stored")
    return {"synced_count": len(all_leads)}


def _incremental_sync(
    account: Account,
    access_key: str,
    secret_key: str,
    base_url: str,
    since_date: str,
    db: Session,
) -> Dict[str, Any]:
    """Incremental sync: search source fields for leads CreatedOn >= since_date.

    This catches newly created leads regardless of which source field contains GGL.
    """
    logger.info(f"LSQ mirror incremental sync for account {account.id} ({account.name}) since {since_date}")

    include_dsi = account.name == "DSI"
    all_leads: Dict[str, Dict[str, Any]] = {}
    search_terms = ["GGL", "Programmatic"]

    for field_name, _ in _SOURCE_FIELDS:
        for term in search_terms:
            found = _search_lsq_by_source_field(base_url, access_key, secret_key, field_name, term, since_date, include_dsi_course_columns=include_dsi)
            for prospect_id, lead in found.items():
                existing = all_leads.get(prospect_id)
                if existing and existing.get("course") and not lead.get("course"):
                    continue
                all_leads[prospect_id] = lead

    # Delete leads in mirror that were created >= since_date (they will be re-upserted)
    db.query(LeadSquaredLead).filter(
        LeadSquaredLead.account_id == account.id,
        LeadSquaredLead.created_on >= since_date,
    ).delete(synchronize_session=False)

    for lead in all_leads.values():
        db.add(
            LeadSquaredLead(
                account_id=account.id,
                **lead,
                synced_at=datetime.utcnow(),
            )
        )

    db.commit()
    logger.info(f"LSQ mirror incremental sync complete: {len(all_leads)} leads")
    return {"synced_count": len(all_leads)}


def sync_account_leads(account_id: int, db: Session = None, full_window_from: str = None) -> Dict[str, Any]:
    """Sync LeadSquared leads for one account into the local mirror.

    Args:
        account_id: Account to sync.
        db: Existing DB session (optional; one is created if not provided).
        full_window_from: If provided, performs a full source-based rebuild from
            this date. Otherwise performs an incremental sync from the most
            recent modified_on in the mirror (minus a 7-day buffer).

    Returns:
        dict with synced_count and error (if any).
    """
    close_db = db is None
    if db is None:
        db = SessionLocal()

    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return {"error": f"Account {account_id} not found"}

        access_key, secret_key, base_url = _get_lsq_credentials(account)
        if not access_key or not secret_key or not base_url:
            return {"error": "LeadSquared credentials not configured"}

        # Default full sync window from account inception
        default_since = "2025-11-28"

        if full_window_from:
            return _full_sync_by_source(account, access_key, secret_key, base_url, full_window_from, db)

        # Incremental: fetch from most recent modified_on minus 7 days
        latest = (
            db.query(LeadSquaredLead)
            .filter(LeadSquaredLead.account_id == account_id)
            .order_by(LeadSquaredLead.modified_on.desc())
            .first()
        )
        if latest and latest.modified_on:
            latest_dt = date.fromisoformat(latest.modified_on)
            from_dt = latest_dt - timedelta(days=7)
            since_date = from_dt.isoformat()
        else:
            since_date = default_since

        return _incremental_sync(account, access_key, secret_key, base_url, since_date, db)

    except Exception as e:
        logger.exception(f"LSQ mirror sync failed for account {account_id}: {e}")
        return {"error": str(e)}
    finally:
        if close_db:
            db.close()


from datetime import datetime


def count_leads_by_course(
    db: Session,
    account_id: int,
    start_date: str,
    end_date: str,
) -> Dict[str, int]:
    """Count GGL/Programmatic leads by resolved course from the local mirror.

    Filters on CreatedOn date, which matches the user's raw-data expectation.
    """
    rows = (
        db.query(LeadSquaredLead)
        .filter(
            LeadSquaredLead.account_id == account_id,
            LeadSquaredLead.created_on >= start_date,
            LeadSquaredLead.created_on <= end_date,
        )
        .all()
    )

    counts: Dict[str, int] = {}
    for lead in rows:
        course = lead.course or lead.source or "Unknown"
        counts[course] = counts.get(course, 0) + 1
    return counts


def get_lead_details(
    db: Session,
    account_id: int,
    start_date: str,
    end_date: str,
) -> List[Dict[str, Any]]:
    """Return lead details from the local mirror for stage/status pivot tables."""
    rows = (
        db.query(LeadSquaredLead)
        .filter(
            LeadSquaredLead.account_id == account_id,
            LeadSquaredLead.created_on >= start_date,
            LeadSquaredLead.created_on <= end_date,
        )
        .all()
    )

    return [
        {
            "source": r.source,
            "student_source": r.student_source,
            "stage": r.student_stage,
            "application_status": r.application_status,
            "created_on": r.created_on,
            "course": r.course,
            "department": _get_dsi_dept(r.course) if account_id == 2 else "",
        }
        for r in rows
    ]


def _get_dsi_dept(course: str) -> str:
    """Resolve DSI department for a course."""
    if not course:
        return ""
    from backend.services.dsi_data import _get_dsi_dept as _dsi_dept
    return _dsi_dept(course)
