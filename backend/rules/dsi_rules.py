"""
DSI Table Rules — single source of truth for InsightDesk.

Logic ported from AI_The_MIS (dist/app.bundle.js). DSI has 5 tables
(Tables 1-5). There is NO DSI Table 6 and NO DSI Table 7.

GST cutoff: 18-Jun-2026 inclusive (no GST on/before, 18% after).
Inception display label: 28-Nov-2025 (GGL_DSI_0901_3103 sheet covers 9-Jan to 31-Mar).
"""

from datetime import date

# ---------------------------------------------------------------------------
# Global constants (shared with DSU)
# ---------------------------------------------------------------------------

DSI_GST_CUTOFF_DATE = date(2026, 6, 18)
GST_MULTIPLIER = 1.18

# Old account date range (from Excel: GGL_DSI_0901_3103)
DSI_OLD_ACCOUNT_START = "2026-01-01"
DSI_OLD_ACCOUNT_END = "2026-03-31"

# New account (live API) starts 1-Apr-2026
DSI_NEW_ACCOUNT_START = "2026-04-01"

# ---------------------------------------------------------------------------
# Department mapping (getDsiFallbackDept)
# ---------------------------------------------------------------------------
DSI_FALLBACK_DEPT = {
    # DSCE = Engineering
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
    # DSIT = Diploma / specific engineering branches
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
    # DSCA = Architecture
    "bachelor of architecture campus 1": "DSCA",
    "b. arch": "DSCA",
    "m.arch": "DSCA",
    "arch": "DSCA",
    # DSCASC - UG
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
    # DSCASC - Masters
    "mba": "DSCASC - Masters",
    "mca": "DSCASC - Masters",
    "m.com": "DSCASC - Masters",
    "m.com ": "DSCASC - Masters",
}

# Department display order (DEPT_ORDER)
DEPT_ORDER = {
    "dsit": 2,
    "dsce": 3,
    "dsca": 4,
    "dscasc - ug": 5,
    "dscasc - masters": 6,
}

# ---------------------------------------------------------------------------
# Course lists for Tables 4 & 5 (per-section)
# ---------------------------------------------------------------------------
DSCE_COURSES = [{"key": "DSCE", "display": "DSCE", "target": 0}]
DSIT_COURSES = [{"key": "DSIT", "display": "DSIT", "target": 0}]
DSCA_COURSES = [
    {"key": "Arch", "display": "Arch", "target": 0},
    {"key": "Bachelor of Architecture Campus 1", "display": "B. Arch", "target": 0},
    {"key": "M.Arch", "display": "M.Arch", "target": 0},
]
DSCASC_UG_COURSES = [
    {"key": "B.Com", "display": "B.Com", "target": 0},
    {"key": "B.Com Evening Programs", "display": "B.Com Evening", "target": 0},
    {"key": "B.Sc (PCM)", "display": "B.Sc (PCM)", "target": 0},
    {"key": "BBA", "display": "BBA", "target": 0},
    {"key": "BCA", "display": "BCA", "target": 0},
    {"key": "BCA Evening Programs", "display": "BCA Evening", "target": 0},
]
DSCASC_MASTERS_COURSES = [
    {"key": "MBA", "display": "MBA", "target": 0},
    {"key": "MCA", "display": "MCA", "target": 0},
    {"key": "M.Com", "display": "M.Com", "target": 0},
]

# Default manual budgets (localStorage defaults from bundle)
DSI_CAMPUS1_ENG_BUDGET_DEFAULT = 1_500_000   # DSCE section
DSI_CAMPUS1_DEG_BUDGET_DEFAULT = 1_000_000   # DSIT section

# ---------------------------------------------------------------------------
# Application Submitted statuses (same as DSU)
# ---------------------------------------------------------------------------
APPLICATION_SUBMITTED_STATUSES = {
    "application fee paid",
    "application submitted",
    "enrolled",
    "partially paid",
}

# ---------------------------------------------------------------------------
# Table 1 — Daily Performance (Yesterday)
# ---------------------------------------------------------------------------
TABLE1 = {
    "purpose": "Course-wise leads & spend by course for yesterday only.",
    "date_logic": "yesterday by default",
    "source_spend": "Google Ads API (GGL_DSI sheets) for the selected day",
    "source_leads": "LeadSquared mirror (LS_DSI) for the selected day",
    "filters": {
        "spend_status": "ONLY enabled/live/active campaigns (yesterday)",
        "monthly_only_rows": "excluded",
        "display": "rows with lead==0 AND spend==0 are hidden",
    },
    "columns": {
        "department": "dsiProgramCourseMap[course] or getDsiFallbackDept(course)",
        "course": "resolved course (DSCE/DSIT collapse engineering branches)",
        "leads": "count of LS_DSI leads mapped to this course for the day",
        "spend": "sum of GST-adjusted Google Ads cost for the day",
        "cpl": "spend/leads if leads>0 else 'No Leads'",
    },
    "gst": "per-day applyGstRule",
    "sort": "DEPT_ORDER then course alphabetically",
}

# ---------------------------------------------------------------------------
# Table 2 — Cumulative Performance
# ---------------------------------------------------------------------------
TABLE2 = {
    "purpose": "Course-wise cumulative leads & spend by course, inception to yesterday.",
    "date_logic": "default: 28-Nov-2025 to yesterday; custom range supported",
    "source_spend": (
        "default range: dsi_table2_historical (exact raw-data match). "
        "custom range: dsi_legacy_spend (Jan-26..Mar-26) + live Google Ads API (Apr-26+)"
    ),
    "source_leads": "LeadSquared mirror (LS_DSI)",
    "filters": {
        "spend_status": "ALL statuses included (no live-only filter for cumulative)",
        "monthly_only_rows": "excluded",
        "display": "rows with lead==0 AND spend==0 are hidden",
    },
    "columns": {
        "department": "dsiProgramCourseMap[course] or getDsiFallbackDept(course)",
        "course": "resolved course (DSCE/DSIT collapse engineering branches)",
        "leads": "cumulative count of LS_DSI leads mapped to this course",
        "spend": "cumulative GST-adjusted Google Ads cost (ALL statuses)",
        "cpl": "spend/leads if leads>0 else 'No Leads'",
    },
    "gst": "per-day applyGstRule",
    "sort": "DEPT_ORDER then course alphabetically",
}

# ---------------------------------------------------------------------------
# Table 3 — Lead Source-Stage Pivot
# ---------------------------------------------------------------------------
TABLE3 = {
    "purpose": "Lead attribution pivot: rows = course (or source) x columns = Student Stage.",
    "source": "LeadSquared mirror only (no spend)",
    "date_logic": "cumulative; optional custom range",
    "row_key": "lead.cleanCourse (mapped) || lead.source (raw)",
    "filters": "counted if rowKey and lead.stage both non-empty",
    "columns": "one per distinct Student Stage, sorted alphabetically",
    "display": "zero values as blank",
    "gst": "N/A",
}

# ---------------------------------------------------------------------------
# Table 4 — Application MIS Overall (Submitted & CPA)
# ---------------------------------------------------------------------------
TABLE4 = {
    "purpose": "Application Submitted count and CPA by department/program (5 sections).",
    "source_spend": "cumulative Table 2 spend per course",
    "source_submitted": "LeadSquared mirror (Application Status in APPLICATION_SUBMITTED_STATUSES)",
    "submitted_keyed_by": "application course column (getDsiRowCourse -> getMappedCourseName with DSI override)",
    "sections": {
        "DSCE": DSCE_COURSES,
        "DSIT": DSIT_COURSES,
        "DSCA": DSCA_COURSES,
        "DSCASC-UG": DSCASC_UG_COURSES,
        "DSCASC-Masters": DSCASC_MASTERS_COURSES,
    },
    "columns": {
        "application_submitted": "count of leads with submitted status mapped to this course",
        "spend": "cumulative Table 2 spend for this course",
        "cpa": "spend/submitted if submitted>0 else 0 (display ₹0)",
        "target": "course.target (currently 0 for all DSI courses)",
    },
    "totals": "per-section totals + grand total",
    "gst": "inherited from Table 2 spend",
}

# ---------------------------------------------------------------------------
# Table 5 — Budget MIS
# ---------------------------------------------------------------------------
TABLE5 = {
    "purpose": "Program-wise media budget summary: status, budget, spend, remaining.",
    "source_spend": "Google Ads API (GGL_DSI sheets) via getDsiCourseSpend",
    "source_budget": (
        "DSCE section -> dsiCampus1EngBudget (default 1,500,000); "
        "DSIT section -> dsiCampus1DegBudget (default 1,000,000); "
        "DSCA/DSCASC-UG/DSCASC-Masters -> budget 0"
    ),
    "sections": "same 5 sections as Table 4",
    "campaign_status": "Live if spend>0 else Paused (NOT GGL status column)",
    "columns": {
        "media_budget_received": "section-level budget (Eng or Deg; 0 for others)",
        "spend": "getDsiCourseSpend(course.key)",
        "remaining_budget": "budget - spend",
    },
    "gst": "per-day applyGstRule",
    "row_filter": "all listed courses shown (no zero-row hiding)",
}