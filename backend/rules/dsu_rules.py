"""
DSU Table Rules — single source of truth for InsightDesk.

Logic ported from AI_The_MIS (dist/app.bundle.js + docs/DSU_TABLE_LOGIC.md +
scripts/validateDsuLogic.js). Numbers are dynamic (computed from raw data);
only the rules/formulas/logic are locked here.

GST cutoff: 18-Jun-2026 inclusive (no GST on/before, 18% after).
Inception: 28-Nov-2025.
Yesterday = system date - 1 at local midnight.
"""

from datetime import date

# ---------------------------------------------------------------------------
# Global constants
# ---------------------------------------------------------------------------

DSU_INCEPTION_DATE = "2025-11-28"
DSU_GST_CUTOFF_DATE = date(2026, 6, 18)   # on or before -> no GST
GST_MULTIPLIER = 1.18

# Old account date range (API-inaccessible; data comes from Excel)
DSU_OLD_ACCOUNT_START = "2025-11-01"
DSU_OLD_ACCOUNT_END = "2026-03-31"

# New account (live API) starts 1-Apr-2026
DSU_NEW_ACCOUNT_START = "2026-04-01"

# ---------------------------------------------------------------------------
# Table 1 — Daily base-campaign metrics (Yesterday / selected day)
# ---------------------------------------------------------------------------
TABLE1 = {
    "purpose": "Course-wise lead count, ad spend and CPL for a single day.",
    "date_logic": "yesterday by default; dropdown allows today or custom range",
    "source_spend": "Google Ads API (campaign-level cost for the selected day)",
    "source_leads": "LeadSquared mirror (CreatedOn == selected day, source contains GGL or Programmatic)",
    "filters": {
        "spend_status": "ONLY enabled/live/active campaigns (status contains enable/live/active)",
        "monthly_only_rows": "excluded",
        "display": "rows with lead==0 AND spend==0 are hidden",
    },
    "columns": {
        "leads": "count of LSQ leads mapped to this course for the day",
        "spend": "sum of GST-adjusted Google Ads cost for the day",
        "cpl": "spend/leads if leads>0 else 'No Leads'",
    },
    "gst": "per-day applyGstRule: cost*1.18 if date > 18-Jun-2026 else cost",
    "sort": "spend descending (default)",
}

# ---------------------------------------------------------------------------
# Table 2 — Cumulative base-campaign metrics (inception -> yesterday)
# ---------------------------------------------------------------------------
TABLE2 = {
    "purpose": "Course-wise cumulative leads, spend and CPL from inception to yesterday.",
    "date_logic": "default: 28-Nov-2025 to yesterday; custom range supported",
    "source_spend": (
        "default range: dsu_table2_historical (exact raw-data match). "
        "custom range: dsu_legacy_spend (Nov-25..Mar-26) + live Google Ads API (Apr-26+)"
    ),
    "source_leads": "LeadSquared mirror (CreatedOn within range, GGL/Programmatic)",
    "filters": {
        "spend_status": "ALL statuses included (no live-only filter for cumulative)",
        "monthly_only_rows": "excluded",
        "display": "rows with lead==0 AND spend==0 are hidden",
    },
    "columns": {
        "leads": "count of LSQ leads mapped to this course in range",
        "spend": "cumulative GST-adjusted Google Ads cost",
        "cpl": "spend/leads if leads>0 else 'No Leads'",
    },
    "gst": "per-day applyGstRule (legacy Excel data is pre-GST, no GST for Nov-25..Mar-26)",
    "sort": "spend descending (default)",
    "grand_total": "must equal the user's raw-data report (currently ~₹40,88,574.90)",
}

# ---------------------------------------------------------------------------
# Table 3 — Lead Source vs Lead Stage pivot
# ---------------------------------------------------------------------------
TABLE3 = {
    "purpose": "Cross-tab of Student Source (rows) x Student Stage (columns) = lead count.",
    "date_logic": "cumulative (inception to yesterday); optional custom range",
    "source": "LeadSquared mirror only (no spend)",
    "filters": {
        "counted_if": "source and stage both non-empty",
        "row_key": "Student Source (raw value)",
    },
    "columns": "one per distinct Student Stage, sorted alphabetically",
    "display": "zero values shown as blank; row/column totals always shown",
    "gst": "N/A",
    "sort": "rows alphabetically by source; stages alphabetically",
}

# ---------------------------------------------------------------------------
# Table 4 — Application Submitted & CPA by Campus
# ---------------------------------------------------------------------------
APPLICATION_SUBMITTED_STATUSES = {
    "application fee paid",
    "application submitted",
    "enrolled",
    "partially paid",
}

CAMPUS4_COURSES = [
    {"key": "B.Tech", "display": "B.Tech", "target": 522},
]
CAMPUS3_COURSES = [
    {"key": "MBA", "display": "MBA", "target": 39},
    {"key": "BCA", "display": "BCA", "target": 30},
    {"key": "BBA", "display": "BBA", "target": 0},
    {"key": "MCA", "display": "MCA", "target": 0},
    {"key": "B.Com", "display": "B.Com", "target": 0},
    {"key": "B.Sc Data Science", "display": "BSc Data Science", "target": 7},
    {"key": "M.Sc Data Science", "display": "MSc Data Science", "target": 0},
    {"key": "B.Sc Cyber Security", "display": "BSc Cyber Security", "target": 0},
    {"key": "M.Sc Cyber Security", "display": "MSc Cyber Security", "target": 0},
    {"key": "B.Sc Biological Sciences", "display": "BSc Biological Sciences", "target": 0},
    {"key": "M.Sc Biological Sciences", "display": "MSc Biological Sciences", "target": 0},
    {"key": "B.Design", "display": "B Design", "target": 0},
    {"key": "JMC", "display": "JMC", "target": 0},
    {"key": "School of Law", "display": "School of Law", "target": 0},
]

TABLE4 = {
    "purpose": "Application Submitted count and CPA by Campus (4 vs 3).",
    "source_spend": "cumulative Table 2 spend per course",
    "source_submitted": "LeadSquared mirror (Application Status in APPLICATION_SUBMITTED_STATUSES)",
    "campus_logic": {
        "Campus 4": ["B.Tech"],
        "Campus 3": "all non-B.Tech courses",
    },
    "submitted_keyed_by": "Student Source mapped to course (Direct Traffic/GGL-DSAT -> B.Tech)",
    "columns": {
        "application_submitted": "count of leads with submitted status mapped to this course",
        "spend": "cumulative Table 2 spend for this course",
        "cpa": "spend/submitted if submitted>0 else 0 (display ₹0)",
        "target": "hardcoded per course",
    },
    "totals": "per-campus section totals + grand total",
    "gst": "inherited from Table 2 spend",
}

# ---------------------------------------------------------------------------
# Table 5 — Campaign Status & Remaining Media Budget
# ---------------------------------------------------------------------------
TABLE5 = {
    "purpose": "Per-course cumulative spend, allocated media budget, remaining budget.",
    "source_spend": "cumulative Table 2 spend per course",
    "source_budget": "dsu_budget_entries summed by campus (Campus 3 / Campus 4)",
    "campus_logic": "same as Table 4 (Campus 4 = B.Tech; Campus 3 = others)",
    "campaign_status": "Live if spend>0 else Paused (bundle behaviour; not GGL status column)",
    "columns": {
        "media_budget_received": "campus-level total from budget entries",
        "spend": "cumulative Table 2 spend for this course",
        "remaining_budget": "campus_budget - campus_total_spend",
    },
    "gst": "inherited from Table 2 spend",
    "row_filter": "all listed courses shown (no zero-row hiding unlike Tables 1/2)",
}

# ---------------------------------------------------------------------------
# Table 6 — Lead Stage Distribution Summary
# ---------------------------------------------------------------------------
TABLE6 = {
    "purpose": "Aggregate count and percentage of leads per distinct Student Stage.",
    "source": "LeadSquared mirror only",
    "date_logic": "cumulative; optional custom range",
    "filters": "only leads with a non-empty stage are counted",
    "columns": {
        "count": "number of leads with that stage",
        "count_pct": "round(count / total * 100)",
    },
    "sort": "count descending, then stage alphabetically",
    "gst": "N/A",
}

# ---------------------------------------------------------------------------
# Table 7 — Monthly Budget Ledger & Spend Balance
# ---------------------------------------------------------------------------
TABLE7 = {
    "purpose": "Monthly reconciliation of received amounts vs Google Ads monthly spend.",
    "source_spend": (
        "Google Ads spend grouped by month (Month+Cost columns). "
        "Includes BOTH daily rows and monthly-only rows (unlike Tables 1-5)."
    ),
    "source_budget": "dsu_budget_entries (manual received amounts)",
    "month_key_format": "MMM-YYYY e.g. Jun-2026",
    "columns": {
        "date": "entry date (DD-MMM-YYYY) or YYYY-MM-01 for virtual rows",
        "amount_received": "individual entry amount",
        "received_monthly": "sum of all entries in that month (rowspan/merged)",
        "invoice": "entry invoice or '-'",
        "campus": "Campus 3 / Campus 4 (default Campus 3 if unrecognized)",
        "google_spend": "monthly Google spend (merged cell)",
        "meta_spend": "0 (no Meta source yet)",
        "total_spend": "google_spend + meta_spend",
        "available_balance": "received_monthly - total_spend",
    },
    "gst": {
        "monthly_only_rows": "18% if month > Jun-2026 else raw cost",
        "daily_rows": "per-day applyGstRule (folded into month)",
    },
    "campaign_mapping": "NONE — Table 7 uses Month+Cost only (no campaign->course)",
    "virtual_rows": "months with spend but no received entry get a virtual row (amount 0, invoice '-', campus '-')",
    "sort": "months chronologically; within month: date asc then Campus 4 before Campus 3",
    "cross_table_note": "Table 7 google spend may differ from Table 2 (unmapped campaigns included in 7 but not 2)",
}