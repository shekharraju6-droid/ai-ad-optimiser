# Agent Rule Book — ChlearSakhaaOps AI (AdOptima)
**Audit date:** 29 June 2026
**Repo:** `AI_The_Optimiser` · `main` @ `312fa99` (+ uncommitted local working-tree changes)
**Status:** Documentation only — no code changed.

---

## 1. Agent Purpose

ChlearSakhaaOps AI (shipped as "AdOptima AI" / "ChlearSakhaaOps AI") is a multi-tenant SaaS agent for the agency **Chlear Digital**. It serves three modules on one codebase, one Postgres (Supabase) database, and one Railway deployment:

1. **AdPulse** — Ad-account health & spend monitoring across Google Ads and Meta Ads, with AI-generated optimization actions (approve/reject queue), per-account OAuth credentials, lead counts from LeadSquared, and billing/balance chips.
2. **InsightDesk** — Course/department MIS reports for two education clients: **DSU** (Dayananda Sagar University) and **DSI** (Dayananda Sagar Institutions), pulling Google Ads spend and LeadSquared leads, with budget ledgers, lead-stage pivots, application-CPA tables, and monthly reconciliation (DSU only).
3. **RevenueOps** — Invoice → payment → reminder workflow for the agency's own billing: clients, invoices, payments, outstanding ageing, reminders (WhatsApp/email via Twilio/SMTP), BM-wise revenue, documents, and settings.

A single user table with role + per-module access flags gates all three modules. Onboarding is via an emailed setup link.

---

## 2. System Architecture

```
GitHub (shekharraju6-droid/ai-ad-optimiser, branch main)
   │  push / auto-deploy
   ▼
Railway (Dockerfile builder, python:3.12-slim)
   │  uvicorn backend.app:app --host 0.0.0.0 --port $PORT
   ▼
FastAPI backend (backend/app.py)
   ├── Routes (backend/routes/*): accounts, auth, audits, oauth, reports,
   │   dsu_report, dsi_report, revenueops, mantri, crm, notifications, etc.
   ├── Services (backend/services/*): connectors, health, billing, auditor,
   │   lsq_mirror, dsu_data, dsi_data, scheduler, oauth, crypto, etc.
   ├── Rules (backend/rules/*): dsu_rules.py, dsi_rules.py (constants only)
   ├── Agent (backend/agent/agent.py): Google Gemini for recommendation text
   └── DB (backend/db/*): SQLAlchemy ORM → Supabase Postgres
        ▲
        │  DATABASE_URL (Supabase transaction pooler, port 6543)
   Supabase (project mfmtilbrpigxlstzgmzd, region ap-southeast-1)
        │
        ▼
   External APIs:
   • Google Ads API v24 (per-account OAuth, Fernet-encrypted creds)
   • Meta Marketing API v18.0 (working tree) / v20.0 (committed main)
   • LeadSquared v2 (accessKey/secretKey in query string)
   • Salesforce REST v59.0 (refresh-token flow; for generic accounts)
   • Twilio WhatsApp
   • SMTP (Office365 for onboarding email; gmail default in notification_dispatch)
   • Google Gemini (recommendation text generation)
   • (Mantri route serves MOCK data today)

Scheduled jobs (APScheduler BackgroundScheduler, started lazily on first HTTP request):
   • schedule_refresher      — every 1 min  — re-reads audit intervals from DB
   • auto_metrics_refresh   — every 15 min — refreshes spend/clicks/CTR/CPA + billing + health badges for every live account
   • lsq_lead_mirror_sync    — every 3 hrs  — incremental LeadSquared sync for DSU & DSI accounts
   • audit_<id>_<platform>  — per-account  — runs audit_account() (interval from DB; floor 15 min)
   • global_audit            — global      — runs audit_all_accounts() (only if global interval > 0)

Frontend: 5 static HTML files served at root by FastAPI —
   • /            → frontend/index.html     (AdPulse)
   • /mis         → frontend/mis.html       (InsightDesk)
   • /revenueops  → frontend/revenueops.html (RevenueOps)
   • /            → frontend/landing.html   (login / onboarding)
   • /onboard     → frontend/onboard.html    (password setup)
   • /privacy     → inline HTML privacy policy (for Meta app compliance)
Auth: JWT in localStorage `adoptima_token`; Bearer header; 30-min token TTL.
```

**Critical deploy note:** The local working tree currently has 9 uncommitted modified files that REVERT post-June-25 commits (Meta v18.0 instead of v20.0, localhost redirect instead of Railway, local LSQ mirror instead of realtime API, onboarding email added). Railway is auto-deployed from `main`, so production runs the committed `main` version. The local server runs the working tree. If you `git add -A && commit && push`, you deploy the regression.

---

## 3. Data Sources

| # | Source | What it provides | Update frequency | Fetcher (file:line) | Supabase table | Dashboard component |
|---|---|---|---|---|---|---|
| 1 | **Google Ads API v24** | Campaign spend (cost_micros), clicks, impressions, conversions, account budget, campaign status, keywords, search terms | Scheduler every 15 min; on-demand refresh button | `connectors.GoogleAdsConnector.fetch_account_metrics` `connectors.py:87`; `fetch_campaigns` `connectors.py:130`; `fetch_billing` `connectors.py:182`; `dsu_data._fetch_google_ads_spend` `dsu_data.py:143`; `dsi_data._fetch_dsi_google_ads_spend` | `accounts` (spend/clicks/impressions/conversions/ctr/cpa/budget/billing_cache columns) | AdPulse tiles + Manage Accounts table; InsightDesk DSU/DSI Tables 1, 2, 4, 5, 7 |
| 2 | **Meta Marketing API** (v18.0/v20.0) | Ad account insights (spend, clicks, impressions, conversions), campaigns, spend_cap, amount_spent | Scheduler every 15 min; on-demand | `connectors.MetaAdsConnector.fetch_account_metrics` `connectors.py:300`; `fetch_campaigns` `connectors.py:331`; `fetch_billing` `connectors.py:361` | `accounts` (same columns, merged with Google when both platforms enabled) | AdPulse tiles (Meta only accounts); billing chip ("USED") |
| 3 | **LeadSquared v2 API** | Leads: prospect, source, created/modified dates, student stage, application status, application course/program | Scheduler every 3 hrs (incremental mirror); manual "Sync Leads" button; realtime fetch on dashboard (committed main only) | `lsq_mirror.sync_account_leads` `lsq_mirror.py:496`; `_incremental_sync` `lsq_mirror.py:423`; `_full_sync_by_source` `lsq_mirror.py`; `dsu_data._fetch_lsq_leads` `dsu_data.py:198`; `_fetch_lsq_leads_direct` `dsu_data.py:231`; `fetch_realtime_lead_counts` (committed main only, removed in working tree) | `leadsquared_leads` (mirror; id, account_id, prospect_id, source, source_campaign, student_source, latest_source, secondary_source, student_stage, application_status, created_on VARCHAR, modified_on VARCHAR, course, raw_json, synced_at) | AdPulse lead tile count; InsightDesk DSU/DSI Tables 1, 2, 3, 4, 6 |
| 4 | **Salesforce REST v59.0** | Leads, opportunities (SOQL queries filtered by Company LIKE account name) | On-demand (generic report view only) | `crm_connectors.SalesforceConnector` `crm_connectors.py:34-156` | None (in-memory) | Generic InsightDesk report (non-DSU/DSI/Mantri accounts) |
| 5 | **Manual inputs (UI)** | DSU budget entries (date/amount/invoice/campus), DSI budget entries (date/amount/invoice/section), RevenueOps clients/invoices/payments/reminders/documents/BMs, settings | User-triggered via forms | `routes/dsu_report.py`, `routes/dsi_report.py`, `routes/revenueops.py` | `dsu_budget_entries`, `dsi_budget_entries`, `rev_clients`, `rev_invoices`, `rev_payments`, `rev_reminders`, `rev_documents`, `users`, `rev_settings`, `client_billing_models` | InsightDesk Tables 5 & 7 (DSU/DSI); entire RevenueOps module |
| 6 | **Hardcoded legacy spend (Excel import)** | Old Google Ads account monthly spend, Nov-25 → Mar-26 (DSU), Jan-26 → Mar-26 (DSI) | One-time seed | `scripts/seed_legacy_spend.py`; `dsu_data._fetch_legacy_spend` `dsu_data.py:1134` | `dsu_legacy_spend` (DSU), `dsi_legacy_spend` (DSI), `dsu_table2_historical`, `dsi_table2_historical`, `dsu_monthly_spend_fixed`, `dsi_monthly_spend_fixed` | DSU/DSI Table 2 (cumulative, default inception range) |
| 7 | **Twilio WhatsApp** | Reminder message delivery | On-demand ("Copy Text" / generate-text endpoint) | `notification_dispatch.send_whatsapp` `notification_dispatch.py:81` | `notification_logs` | RevenueOps Reminders panel |
| 8 | **SMTP (Office365 / Gmail)** | Onboarding invitation email; notification emails | On user creation; on notification events | `onboarding_email.send_onboarding_email` `onboarding_email.py`; `notification_dispatch.send_email` `notification_dispatch.py:35` | `notification_logs` | User management (Landing page + RevenueOps Users panel) |
| 9 | **Google Gemini** | Recommendation/action reason text generation | On-demand inside auditor | `agent/agent.py:38,77` | None (in-memory) | AdPulse Approval Queue (action `reason` text) |
| 10 | **Mantri route (MOCK)** | Lead-status-by-platform counts/percentages | Static mock | `routes/mantri.py:104-194` | None | InsightDesk Mantri Developers account view |

---

## 4. Current Business Logic

### 4.1 AdPulse — ad health

**API health badge** (`health.compute_api_health` `health.py:84`):
- `api_success=False` → DISCONNECTED/red — "API call failed — auth, token, or permission issue."
- `last_sync_at=None` → WARNING/yellow — "API responded but last sync time is missing."
- `hours_since_sync > 3` (STALE_SYNC_HOURS) → WARNING/yellow.
- Else → GOOD/green.

**Performance health badge** (`health.compute_perf_health` `health.py:149`), priority-ordered:
1. `api_success=False` → UNKNOWN/grey.
2. `campaign_active=False` (account.is_live=False) → CRITICAL/red — "paused/suspended".
3. `spend < 1 AND progress ≥ 50%` → CRITICAL (zero spend past half-day).
4. `impressions ≤ 0 AND progress ≥ 50%` → CRITICAL.
5. `daily_budget>0 AND progress≥50% AND pacing<20%` → CRITICAL.
6. `spend<₹100 AND progress≥50% AND no daily_budget` → CRITICAL (fallback).
7. `spend<1 AND progress≥30%` → WARNING (zero spend past 30%).
8. `impressions≤0 AND progress≥30%` → WARNING.
9. `daily_budget>0 AND progress≥30% AND pacing<25%` → WARNING.
10. `spend<₹50 (micro) AND progress≥30%` → WARNING (×2 rules, one with budget, one without — DUPLICATE).
11. `impressions≥500 AND clicks≤0` → WARNING.
12. `clicks≥20 AND effective_leads≤0` → WARNING, or CRITICAL if `spend ≥ 1.5× target_cpa`.
13. `target_cpa>0 AND spend≥0.7×target_cpa AND leads=0` → WARNING.
14. `cpa ≥ 1.5×target_cpa` → CRITICAL; `≥ 1.2×target_cpa` → WARNING.
15. Else → GOOD.

`progress` = fraction of active-day elapsed. Default active window 9–21 IST; **scheduler passes `active_start=0, active_end=23`** (`scheduler.py:84,112`) — i.e. 24h. `now` is IST (UTC+5:30). `MIN_MEANINGFUL_SPEND_WARNING=₹50`, `_CRITICAL=₹100`, `MICRO_SPEND_THRESHOLD=₹50`, `PACING_WARNING_RATIO=0.25`, `PACING_CRITICAL_RATIO=0.20`.

**Status enum mapping** (`scheduler.py:88-95`):
- API DISCONNECTED → `AccountStatus.DISCONNECTED`
- Perf CRITICAL → `AccountStatus.CRITICAL`
- Perf WARNING/UNKNOWN → `AccountStatus.WARNING`
- else → `AccountStatus.HEALTHY`

### 4.2 Spend tracking

- Stored on `accounts.spend` (Float, default 0).
- Scheduler (`scheduler.py:62-72`) per platform per day:
  - If account has **only one platform**: spend = that platform's metrics.spend (overwrite).
  - If account has **both google AND meta**: spend += platform's metrics.spend (accumulate, NOT reset first — **RISK**: scheduler runs every 15 min for "today"; on each run it ADDS today's spend to the already-stored today's spend → double/triple counting within a day). The committed main code does NOT reset spend to 0 before accumulating for dual-platform accounts.
- AdPulse "today" preset uses `start_date=end_date=today` (IST midnight).
- DSU/DSI spend from Google Ads API uses `segments.date BETWEEN start AND end` GAQL query (`dsu_data.py:169-178`), with **per-day GST**: `if spend_date >= "2026-06-19": cost × 1.18` (`dsu_data.py:190-191, 841-857`). Cutoff `DSU_GST_TRANSITION_DATE="2026-06-19"`, `GST_MULTIPLIER=1.18`.
- DSU customer ID is hardcoded `"2909919094"` (`dsu_data.py:167`). DSI customer ID is hardcoded `"1917462211"` (`dsi_data.py:23`).
- Legacy spend (Nov-25 → Mar-26) comes from `dsu_legacy_spend` / `dsi_legacy_spend` tables, seeded from Excel.

### 4.3 Balance / billing tracking

**Google Ads billing** (`connectors.fetch_billing` `connectors.py:182`):
- Queries `account_budget` for `adjusted_spending_limit_micros` (total budget) and `approved_start_date_time`.
- Available balance = total_budget − spend_since_budget_start (separate GAQL query for cost_micros since budget start date).
- Returns `billing_type="prepaid"`, `amount=balance`, `total_budget`, `spend_since_budget_start`, `budget_start_date`.
- Failure → `billing_type="unknown"`, `amount=None`, `status="unavailable"`.

**Meta billing** (`connectors.MetaAdsConnector.fetch_billing` `connectors.py:361`):
- `account.api_get(fields=["spend_cap","spend","currency","amount_spent"])`.
- If `spend_cap>0` → `postpaid`, amount = `amount_spent`.
- If `amount_spent>0` → `postpaid`, amount = `amount_spent`.
- Else → `unknown/unavailable`.
- **Meta has no prepaid balance concept** in the standard API.

**Billing chip display** (`billing.build_billing_display` `billing.py:33`):
- Parses `account.billing_cache` JSON.
- Prepaid: `"BAL ₹12.5K / ₹1.4L"` (balance / total_budget); color red if `amount≤0`, yellow if `<10% of total_budget` or `<₹500`, grey if None, else neutral.
- Postpaid: `"USED ₹4.2K"`; always neutral.
- Unavailable: `"BAL ---"` / `"USED ---"` / `"BILL ---"`, grey.
- Format: `₹<int>` if <1000, `₹X.XK` if <1L, `₹X.XL` if ≥1L.

### 4.4 Payment tracking (RevenueOps)

- `RevInvoice.invoice_amount` (billed), `amount_received` (sum of linked `RevPayment.amount`), `outstanding_amount = invoice_amount − amount_received`.
- `overdue_days` computed in `_recalc_invoice` (`revenueops.py:363`): `(today − due_date).days`. Reset to 0 if not yet due.
- `invoice_status` enum: not_raised → invoice_raised → sent_to_client → partially_paid → paid; or overdue; or disputed; or cancelled; or credit_note_issued.
- Dashboard KPIs (`revenueops.py:906-984`):
  - `total_billed = Σ invoice_amount` (excludes cancelled).
  - `total_collected = Σ Σ payments.amount` (excludes cancelled).
  - `total_outstanding = total_billed − total_collected`.
  - `collection_pct = total_collected/total_billed × 100` (0 if no billed).
  - `total_overdue = Σ outstanding_amount` for invoices where `invoice_status==OVERDUE` OR (`outstanding>0 AND due_date<today`).
  - `expected_collection_week = total_outstanding × 0.2` — **PURE GUESS (20%)**.
  - `expected_collection_month = total_outstanding × 0.5` — **PURE GUESS (50%)**.
  - `monthly_billed/collected` filter by `invoice_date >= this_month_start`.
- BM-scoped view: if `user.rev_role == business_manager`, invoices filtered to clients where `business_manager_id == user.id`.

### 4.5 MIS matching (InsightDesk)

**DSU lead filter** (`lsq_mirror._is_ggl_or_programmatic` `lsq_mirror.py:204`):
- `"GGL" in (source + student_source).upper()` OR `"PROGRAMMATIC"` in same. Does NOT use `latest_source`/`secondary_source` (intentional — those reflect later attribution).
- `EXCLUDED_SOURCES = {"DSPS-GGL"}` (`dsu_data.py:110`) — always excluded.

**DSI lead filter** (`lsq_mirror._is_dsi_source` + `_is_dsi_included_lead` `lsq_mirror.py:218-245`):
- DSI CRM view includes: `GGL-DSI` (all campaigns), `CHL_DISPLAY` (all campaigns), `Programmatic` (ONLY 11 whitelisted campaigns in `DSI_PROGRAMMATIC_CAMPAIGN_WHITELIST` `lsq_mirror.py:46-58`).
- This is STRICTER than DSU.

**Course mapping**:
- DSU: `SOURCE_TO_COURSE` dict (18 entries, `dsu_data.py:87-107`) + `_map_campaign_to_course` keyword substring match (`dsu_data.py:113-128`, 84 keywords in `CAMPAIGN_KEYWORDS`).
- DSI: `DSI_SOURCE_TO_COURSE` (11 entries, `dsi_data.py:106-118`) + `_map_dsi_campaign_to_course` token-based match (`dsi_data.py:183-219`, 57 keywords) + `_rollup_to_dept` + `DSI_FALLBACK_DEPT` (45 entries, `dsi_data.py:121-165`).

**Date windows**:
- DSU `computeDSUDateRange` (`mis.html:389-407`): all presets END ON YESTERDAY (`end.setDate(end.getDate()-1)`). Inception start = `2025-11-28`. `today` preset has start=today, end=yesterday → **start>end, returns empty**.
- DSI `computeDSIDateRange` (`mis.html:1095-1112`): identical to DSU after the local fix applied today (was buggy before: end stayed at today).
- AdPulse `computeDateRange` (`index.html:687-701`): today preset = today→today; yesterday = yesterday→yesterday; last7 = today−6 → today. No `inception` preset (uses `allTime` = 2020-01-01 → today).

### 4.6 Good / Warning / Critical conditions

| Condition | Module | Output | File:line |
|---|---|---|---|
| Spend=0 past 50% of active day | AdPulse perf | CRITICAL/red | `health.py:227` |
| Impressions=0 past 50% | AdPulse perf | CRITICAL | `health.py:237` |
| CPA ≥ 1.5×target | AdPulse perf + auditor | CRITICAL | `health.py:360`, `auditor.py:234` |
| CPA ≥ 1.2×target | AdPulse perf + auditor | WARNING | `health.py:368`, `auditor.py:234` (same rule, different threshold) |
| Spend pacing <20% expected past 50% | AdPulse perf | CRITICAL | `health.py:247` |
| Clicks≥20, leads=0, spend≥1.5×target_cpa | AdPulse perf | CRITICAL | `health.py:332` |
| Campaign paused | AdPulse perf | CRITICAL | `health.py:192` |
| API call failed | AdPulse API | DISCONNECTED/red | `health.py:105` |
| Sync >3 hrs old | AdPulse API | WARNING/yellow | `health.py:127` |
| Billing balance ≤0 (prepaid) | AdPulse billing chip | red | `billing.py:96-97` |
| Billing balance <10% of budget or <₹500 | AdPulse billing chip | yellow | `billing.py:98-101` |
| CPL with leads=0 | InsightDesk | "No Leads" text | `dsu_data.py:409`, `mis.html:529` |
| CPA with submitted=0 | InsightDesk Table 4 | "₹0" display | `dsu_rules.py:137` |
| Lead=0 AND spend=0 | InsightDesk Tables 1, 2 | row hidden | `dsu_data.py:407`, `dsu_rules.py:42` |
| Invoice overdue >60d | RevenueOps | "60+ days" dark-red badge | `revenueops.html:477` |
| Invoice on time (overdue_days≤0) | RevenueOps | "On time" green | `revenueops.html:477` |

### 4.7 Zero-data / missing-data / fallback

- **AdPulse**: `api()` helper (`index.html:516-535`) on 401 clears token + shows auth. On other errors, the calling function typically `catch(e){alert(e.message)}` or silently swallows. `formatMoney(null)` → "Rs 0". `formatNum(null)` → 0. Lead tile: on API error → "Leads: -"; non-live account → "0".
- **InsightDesk**: `_fetch_lsq_leads` (`dsu_data.py:198`) falls back to `_fetch_lsq_leads_direct` (live API) if the local mirror is empty for that account. Direct API has a 30-min in-memory cache. If LSQ creds missing → returns `{}` (all zeros).
- **Google Ads spend**: if creds missing, `_get_dsu_account_creds` raises ValueError → calling endpoint returns empty spend dict. No graceful degradation — the report just shows zeros.
- **DB fallback** (`database.py:51-81`): tries PostgreSQL → if port 5432, retries on 6543 pooler → falls back to SQLite at `ADOPTIMA_DB_PATH`. Logged warning if DATABASE_URL was set but PG failed.
- **Billing**: failures → `billing_type="unknown"`, displayed as "BILL ---" grey chip. Does NOT fall back to using `account.spend` as "USED" (deliberate — `billing.py:59` comment).
- **RevenueOps**: `fmt(null)` → "—". Dashboard recalculates invoice state on every dashboard call (`_recalc_invoice`).

---

## 5. Status Label Logic

| Status name | Meaning | Trigger condition | Data required | Where it appears | Current weakness |
|---|---|---|---|---|---|
| GOOD (green) | API healthy, perf within range | All health checks pass | api_success, last_sync<3h, spend>0, impr>0, cpa<1.2×target | AdPulse tile badges (API + ADS) | No distinction between "no data yet" and "actually good" |
| WARNING (yellow) | Suboptimal but not critical | Any WARNING rule fires | varies | AdPulse tile badges | 10+ overlapping WARNING rules; first match wins → later (more severe) rules masked |
| CRITICAL (red) | Action needed now | Any CRITICAL rule fires | varies | AdPulse tile badges | Micro-spend rule duplicates (lines 298-315) — same outcome twice |
| DISCONNECTED (red) | API auth/token/permission failed | `api_success=False` | api call result | AdPulse API badge | Does not distinguish auth vs token-expiry vs network |
| UNKNOWN (grey) | Can't evaluate perf | `api_success=False` in perf layer | api call result | AdPulse ADS badge | Same condition as DISCONNECTED but different label — confusing |
| Live (green) | Account has live OAuth creds | `is_live=True` | `google_is_live OR meta_is_live` | AdPulse tile footer + Manage Accounts "Mode" | Tile shows "Live" even if both API calls are failing |
| Not Connected (amber) | No live creds | `is_live=False` | | AdPulse tile footer + Manage Accounts "Mode" | |
| BAL ₹X / ₹Y | Prepaid balance | Google account_budget API success | billing_cache | AdPulse billing chip | Only Google has real prepaid; Meta always postpaid/unknown |
| USED ₹X | Postpaid spend used | Meta spend_cap/amount_spent>0 | billing_cache | AdPulse billing chip | "USED" is cumulative since account start, not "today" |
| BILL --- / BAL --- / USED --- | Billing unavailable | API failed or no billing_cache | | AdPulse billing chip | User can't tell if it's "no data yet" vs "API broken" |
| No Leads | CPL undefined (0 leads) | `leads==0` | LSQ lead count | InsightDesk Tables 1, 2 | Same label for "zero leads today" and "mirror broken" |
| On time (green) | Invoice not overdue | `overdue_days ≤ 0` | due_date, today | RevenueOps overdue badge | Negative overdue_days (paid early) still show "On time" |
| Due soon (blue) | Due within 3 days | `-3 ≤ overdue_days ≤ 0` | due_date, today | RevenueOps overdue badge | |
| 1-7d / 8-15d / 16-30d / 31-60d / 60+ | Overdue ageing buckets | `overdue_days > 0` | due_date | RevenueOps overdue badge | Boundaries: >0, >7, >15, >30, >60 |
| Live data (green) / Sample data (amber) | Mantri route data source | `data.configured` flag | mock flag | Mantri InsightDesk view | Always "Sample data" — route serves mock |

---

## 6. Card Logic (AdPulse + RevenueOps KPIs)

### AdPulse top KPI grid (`index.html:767-771`)

| Card | Formula | Zero/missing | API fail |
|---|---|---|---|
| Total Accounts | `data.total_accounts \|\| 0` | shows 0 | shows 0 (summary endpoint) |
| Total Spend | `formatMoney(data.total_spend)` | "Rs 0" | "Rs 0" |
| Total Conversions | `formatNum(data.total_conversions)` | 0 | 0 |
| Avg CTR | `total_impressions ? (total_clicks/total_impressions)×100 : 0` → 2dp+"%" | "0.00%" | "0.00%" |

### AdPulse account tile (`index.html:818-862`)

| Field | Formula | Zero/missing |
|---|---|---|
| Spend | `formatMoney(a.spend)` | "Rs 0" |
| Conversions | `formatNum(a.conversions)` | 0 |
| CTR | `formatPct(a.ctr)` | "0.00%" |
| CPA | `formatMoney(a.cpa)` | "Rs 0" |
| Leads | live→"..."→`formatNum(data.leads)`; non-live→"0"; error→"Leads: -" | "0" or "-" |
| Last Sync | `formatDate(a.last_sync_at)` Asia/Kolkata | "Never" |
| Billing chip | from `a.billing` object | "BILL ---" grey |

### AdPulse account detail KPIs (`index.html:946-949`)

Same as tile (Spend/Conversions/CTR/CPA) but for a single account with detail date range.

### RevenueOps 14 KPI cards (`revenueops.html:539-553`)

| Card | Formula | Zero/missing |
|---|---|---|
| Total Billed | `fmt(k.total_billed)` | "—" |
| Total Collected | `fmt(k.total_collected)` | "—" |
| Outstanding | `fmt(k.total_outstanding)` | "—" |
| Overdue | `fmt(k.total_overdue)` | "—" |
| Collection % | `k.collection_percentage + "%"` + stat-bar | "0%" |
| Monthly Billed | `fmt(k.monthly_billed)` | "—" |
| Monthly Collected | `fmt(k.monthly_collected)` | "—" |
| Active Clients | `k.active_client_count` + sub `${k.clients_no_invoice} without invoice` | 0 + "0 without invoice" |
| Overdue Invoices | `k.overdue_invoices` | 0 |
| Partially Paid | `k.partially_paid_count` | 0 |
| Disputed | `k.disputed_count` | 0 |
| Expected This Week | `fmt(k.expected_collection_week)` = `total_outstanding × 0.2` | "—" |
| Expected This Month | `fmt(k.expected_collection_month)` = `total_outstanding × 0.5` | "—" |

`fmt(n)` = `n!=null ? "INR " + en-IN(2dp) : "—"`.

---

## 7. Payment Tracking Logic

### Prepaid accounts (Google Ads)
- Billing API returns `adjusted_spending_limit_micros` = total budget, `approved_start_date_time` = budget start.
- Available balance = `total_budget − Σ cost_micros since budget_start`.
- Display: "BAL ₹X / ₹Y" where Y = total_budget.
- Color: red if balance ≤0, yellow if <10% of total or <₹500, neutral otherwise.

### Postpaid accounts (Meta Ads)
- Meta Marketing API has no "balance" — only `spend_cap` (cap) and `amount_spent` (cumulative).
- Display: "USED ₹X" where X = `amount_spent` (cumulative since account creation, NOT today).
- Always neutral color.

### Spend calculation
- Per platform per day from `metrics.cost_micros / 1_000_000`.
- Scheduler accumulates for dual-platform accounts (BUG: no reset → double-counting within a day).
- DSU/DSI spend has GST applied per-day: `×1.18` if date ≥ 2026-06-19, raw otherwise.

### Due amount
- RevenueOps: `outstanding_amount = invoice_amount − Σ payments.amount`.
- `overdue_days = (today − due_date).days`.
- `invoice_status` transitions: not_raised→invoice_raised→sent_to_client→partially_paid→paid; or overdue/disputed/cancelled/credit_note.

### Payment alerts
- Reminders created with type (due_in_3_days, due_today, overdue_7/15/30_days, invoice_not_raised, followup_pending, payment_promised), priority (low/medium/high/critical), status (open/snoozed/done).
- `checkDueReminders` polls `/reminders/due-today` every 60s (`revenueops.html:1048`); if any → popup.
- WhatsApp text generation via `/reminders/{id}/generate-text?channel=whatsapp` → copies to clipboard.

### Assumptions in current code
- "Expected This Week" = 20% of outstanding — **pure guess, no client confirmation data**.
- "Expected This Month" = 50% of outstanding — **pure guess**.
- Meta "USED" amount is cumulative lifetime, not period — **misleading**.
- Google prepaid balance assumes a single active account_budget — if multiple exist, takes first ACTIVE then first row fallback.

---

## 8. MIS Logic

### Import
- Legacy spend (Nov-25 → Mar-26) seeded once via `scripts/seed_legacy_spend.py` into `dsu_legacy_spend` / `dsi_legacy_spend` tables.
- Historical exact cumulative (Table 2 default range) seeded into `dsu_table2_historical` / `dsi_table2_historical`.
- Monthly fixed spend (Nov-25 → May-26 DSU, Jan-26 → Mar-26 DSI) into `dsu_monthly_spend_fixed` / `dsi_monthly_spend_fixed`.
- Live spend (Apr-26 onward) from Google Ads API at report-load time.
- Budget entries manual via UI (DSU: date/amount/invoice/campus; DSI: date/amount/invoice/section).

### Match with ad data
- Google Ads campaign name → course via keyword substring match (`_map_campaign_to_course` / `_map_dsi_campaign_to_course`).
- LeadSquared `Source` field → course via `SOURCE_TO_COURSE` dict, fallback to campaign-name mapper.
- DSI adds `SourceCampaign`, `mx_Application_Course`, `mx_Application_Program` resolution chain (`lsq_mirror.py:161-186`).

### Mandatory fields
- Lead: `ProspectID`, `Source`, `CreatedOn` (always fetched).
- DSI additionally: `SourceCampaign`, `mx_Application_Course`, `mx_Application_Program`, `mx_Student_Stage`, `mx_Application_Status`.
- Budget entry: `date`, `amount` (required), `invoice`/`campus`/`section` (optional).

### Validation present
- LSQ date parsing tries 5 formats, falls back to `value[:10]` (`lsq_mirror.py:88-98`).
- IST conversion (+5:30) applied to CreatedOn/ModifiedOn.
- Month-key normalization handles 2-digit year, case-insensitive month names (`dsu_data.py:923-944`).

### Validation missing
- No uniqueness guard on `prospect_id` across sync runs (caused the sequence-desync duplicate-key bug).
- No check that `account_id` in `leadsquared_leads` matches the account that the lead was synced from.
- No schema migration tool — `Base.metadata.create_all` only creates missing tables; column adds are silent no-ops on Postgres.
- No validation that a Google customer ID is real before storing (placeholder `"dsi-google"` exists in seed data).
- No retry/backoff on `_recalc_invoice` failure in the dashboard endpoint.

---

## 9. AdPulse Logic

### What AdPulse checks
- Per-account metrics (spend, clicks, impressions, conversions, CTR, CPA) from Google/Meta APIs.
- Billing/balance from Google `account_budget` / Meta `spend_cap`.
- Lead counts from LeadSquared (realtime on committed main; mirror on working tree).
- Campaign-level audit: setup (conversion tracking, landing page 404, negative keywords, broad match, UTM), performance (budget burn, high CPA, zero conversions, low CTR, paused with spend), keyword analysis (expensive/no-conversion/low-quality), search-term analysis (irrelevant terms).
- Health badges: API connection + performance.

### How often
- Scheduler `auto_metrics_refresh` every 15 min.
- Scheduler `audit_<id>` every `max(15, audit_interval_minutes)` min (per-account).
- Manual "Refresh All" button and per-tile refresh.
- Manual "Run Audit" button (global + per-account).

### Platforms
- Google Ads (OAuth, per-account creds, developer token required).
- Meta Ads (OAuth, per-account app ID/secret, ad account ID required).
- Both can be enabled on the same account; metrics accumulated.

### Healthy
- API success + sync <3h + spend>0 + impressions>0 + no critical perf rule fires.

### Risky (WARNING)
- Sync >3h, zero spend/impressions at 30% of day, micro-spend, 500+ impr but 0 clicks, 20+ clicks but 0 leads, CPA 1.2-1.5× target.

### Failed (CRITICAL/DISCONNECTED)
- API call failed → DISCONNECTED.
- Campaign paused, zero spend/impressions at 50% of day, CPA ≥1.5×target, spend≥1.5×target with 0 leads.

### What may produce wrong status
1. **Dual-platform spend accumulation BUG**: scheduler adds instead of overwriting for both-platform accounts → inflated spend → false CRITICAL on CPA.
2. **"today" preset in DSU/DSI**: start=today, end=yesterday → start>end → empty results (DSU) / was-buggy-but-now-fixed (DSI after today's local edit).
3. **Micro-spend duplicate rules** (`health.py:298-315`): two identical WARNING outcomes for the same condition.
4. **Scheduler always passes active_start=0, active_end=23** — so progress is calculated over 24h, but thresholds (30%/50%) were designed for a 12h active window. A campaign starting at 9am would show 50% progress at noon under 24h, but only ~8% under 12h → false WARNING/CRITICAL early in the day.
5. **`is_live` gates "Live" badge but not health**: an account can show "Live" with all-red health badges if tokens expired after initial connection.

---

## 10. Error Handling

| Failure point | Current handling | Recommended |
|---|---|---|
| Google/Meta API auth failure | `is_valid=False`, `fetch_account_metrics` returns `{"error": str(e)}`. Scheduler sets `status=DISCONNECTED`, stores `last_sync_error`. Tile shows DISCONNECTED badge. | OK. Add token-expiry detection (401 vs other) to suggest re-auth. |
| Empty API response (0 campaigns) | Auditor loops over empty list → 0 actions. Health layer treats as 0 spend/impressions → may fire WARNING/CRITICAL for "zero spend past 50%". | Distinguish "API returned 0 campaigns" from "API failed". Log explicitly. |
| Supabase read error | SQLAlchemy raises → endpoint 500. Frontend `catch(e){alert(e.message)}`. No retry. | Add connection retry + user-friendly toast. |
| Supabase write error (sequence desync) | `IntegrityError` → sync function catches + logs error, returns `{"error": str(e)}`. Mirror stays stale. **No `setval()` fix logic in code** — must be run manually. | Add `SELECT setval('<seq>', max(id))` after any bulk insert. Add startup self-heal. |
| Wrong date range | DSU `today` preset → start>end → empty table, no error. AdPulse `yesterday` → yesterday→yesterday, fine. | Validate start≤end in `computeDSUDateRange`; show toast if invalid. |
| Missing client mapping (campaign→course) | `_map_campaign_to_course` returns `None` → lead counted under raw `source` string. Spend row skipped. | Log unmapped campaigns for review. |
| Invalid campaign name | Treated as `None` course → "Unknown" bucket. | Same as above. |
| Railway deployment issue (502) | `/health` returns 200 when app is up. No healthcheckPath in railway.json → Railway uses TCP check. | Add `healthcheckPath: /health` to railway.json. |
| Env var missing | `ADOPTIMA_JWT_SECRET` defaults to `"change-me-in-production"` (INSECURE). `ADOPTIMA_SECRET_KEY`/`ADOPTIMA_SALT` have hardcoded weak defaults. `SMTP_USER`/`SMTP_PASS` blank → email silently fails, returns `{"sent": False, "error": "..."}`. | Fail fast on missing JWT secret in production. Log SMTP failures to notification_logs. |
| Cron job not running | Scheduler starts lazily on first HTTP request. If no traffic after Railway restart, scheduler never starts. No alerting. | Use FastAPI `@app.on_event("startup")` instead of lazy middleware. Add heartbeat log. |
| LSQ API 500 on custom-field search | `_search_lsq_by_source_field` catches + logs warning, skips that field, continues with others (`lsq_mirror.py:296-298`). | OK. |
| LSQ mirror stale (sync failed) | `_fetch_lsq_leads` checks if mirror has ANY rows for the account; if empty → falls back to direct API. If mirror has old rows but no recent ones → returns stale counts with no warning. | Add `max(synced_at)` check; warn if >6h old. |

---

## 11. Hidden Assumptions

| # | Assumption | Where | Risk |
|---|---|---|---|
| 1 | Zero spend = campaign is broken (not "budget exhausted today" or "new campaign") | `health.py:217-234` | **Risky** — new campaigns will show CRITICAL on day 1. |
| 2 | No data means "healthy enough to skip" | AdPulse summary shows 0s without any "no data" indicator | **Risky** — user can't distinguish "0 spend" from "API down". |
| 3 | Missing API response = zero | `formatMoney(null)→"Rs 0"`, `formatNum(null)→0` | **Risky** — masks failures. |
| 4 | 24h window is always enough | Scheduler passes `active_start=0, active_end=23` | **Risky** — thresholds tuned for 12h; 50% of 24h = noon, not end-of-day. |
| 5 | Client mapping always exists | `_map_campaign_to_course` returns `None` silently | **Risky** — unmapped spend disappears from Table 1. |
| 6 | Campaign naming is always correct | Keyword substring match on campaign name | **Risky** — "MBA" matches inside "BBA" if order is wrong (it isn't, but fragile). |
| 7 | Google customer IDs are real | Seed data has `"dsi-google"`, `"tlg-meta"` placeholders | **Dangerous** — live API calls fail for these accounts. |
| 8 | PostgreSQL sequence stays in sync | No `setval()` anywhere | **Dangerous** — already caused the June 28 zero-leads bug. |
| 9 | `create_all` applies schema changes | `init_db()` only creates missing tables | **Dangerous** — column adds silently ignored on Postgres. |
| 10 | Meta "amount_spent" = today's spend | Billing chip shows "USED ₹X" | **Risky** — it's lifetime spend, not today. |
| 11 | Expected collection = 20%/50% of outstanding | `revenueops.py:982-983` | **Risky** — pure guess, not data-driven. |
| 12 | `is_live` means "healthy" | Tile shows "Live" green even with red badges | **Safe** — "Live" means creds exist, badges show health separately. |
| 13 | All accounts use IST | `_now_ist()` hardcoded UTC+5:30 | **Safe** — all current clients are India-based. |
| 14 | GST applies from 19-Jun-2026 | `DSU_GST_TRANSITION_DATE="2026-06-19"` | **Safe** — business rule confirmed. |
| 15 | Inception = 28-Nov-2025 (DSU) / 08-Jan-2026 (DSI) | hardcoded in rules + frontend | **Safe** — confirmed by client. |
| 16 | DSI programmatic leads only from 11 whitelisted campaigns | `DSI_PROGRAMMATIC_CAMPAIGN_WHITELIST` | **Safe** — matches CRM view. |
| 17 | Scheduler runs after Railway restart | Lazy start on first HTTP request | **Risky** — if no traffic, no scheduler. |
| 18 | `ADOPTIMA_SCHEDULER_ENABLED` controls scheduler | `.env.example` documents it; code never reads it | **Dangerous** — documentation lies; scheduler always starts. |
| 19 | Working tree == deployed code | 9 uncommitted files differ from `main` | **Dangerous** — local ≠ production; pushing deploys regression. |
| 20 | `.env` is gitignored and absent from repo | Present on disk with live DB password + Gemini key | **Risky** — if accidentally committed, secrets leak. |

---

## 12. Bugs and Logic Risks

| # | Problem | Why it's wrong | File:function | Business impact | Recommended correction |
|---|---|---|---|---|---|
| 1 | **Dual-platform spend double-counting** | Scheduler adds platform spend to `account.spend` every 15 min without resetting. For accounts with both Google+Meta, each run adds today's spend again. | `scheduler.py:69-72` | Inflated spend → false CRITICAL on CPA, wrong dashboard totals. | Reset `account.spend=0` before accumulating when both platforms enabled, OR overwrite per-platform and sum at read time. |
| 2 | **PostgreSQL sequence desync** | Manual ID inserts (seed scripts) don't advance the SERIAL sequence. Next ORM insert collides with existing ID → `UniqueViolation` → LSQ sync fails silently → mirror stale → zero leads. | `database.py` (no setval); `lsq_mirror._incremental_sync:491` | **Already happened** (June 28 zero-leads). DSU/DSI reports show 0 for recent days. | Add `SELECT setval('<table>_id_seq', (SELECT max(id) FROM <table>))` in `init_db()` for every table. |
| 3 | **DSU "today" preset returns empty** | `computeDSUDateRange('today')` sets start=today, end=yesterday → start>end → GAQL `BETWEEN` returns nothing. | `mis.html:396` | DSU Table 1 "Today" shows zeros. | Set `end=today()` for the "today" preset (don't shift end to yesterday for this case). |
| 4 | **24h active window vs 12h thresholds** | Scheduler passes `active_start=0, active_end=23`. Health layer computes progress over 24h. Thresholds (30%/50%) were designed for 12h → 50% of 24h = 12:00 noon → false WARNING at noon for zero-spend campaigns. | `scheduler.py:84,112`; `health.py:58-77` | False warnings/criticals early in the day. | Either pass the real campaign schedule (9-21) or recalibrate thresholds for 24h (e.g. warn at 60%, critical at 80%). |
| 5 | **Duplicate micro-spend WARNING rules** | Lines 298-315 in `health.py` have two identical WARNING outcomes for "micro-spend at 30%". First matches, second is dead code. | `health.py:298-315` | Dead code; no runtime impact but confusing. | Remove one. |
| 6 | **No schema migration** | `Base.metadata.create_all()` only creates missing tables. New columns on existing models are silently ignored on Postgres. | `database.py:100-108` | Adding a column to a model does nothing in production → feature appears broken. | Add Alembic or a `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN IF NOT EXISTS` helper. |
| 7 | **Meta "USED" shows lifetime spend** | `fetch_billing` returns `amount_spent` (cumulative since account creation) as the chip amount. Label says "USED" implying period spend. | `connectors.py:384-389`; `billing.py:113-119` | Misleading — user thinks ₹50L was spent today. | Query `insights` for period spend instead of `amount_spent`; label as "USED (lifetime)" or filter by date. |
| 8 | **"Expected collection" is a guess** | `total_outstanding × 0.2` and `× 0.5` with no client/payment-history basis. | `revenueops.py:982-983` | KPIs that look real but aren't. | Replace with `Σ outstanding where due_date ≤ today+7` (week) / `≤ today+30` (month). |
| 9 | **Placeholder customer IDs in seed data** | `"dsi-google"`, `"tlg-meta"` etc. are not valid Google/Meta IDs. Live API calls fail for these accounts. | `seed_accounts.py:63,140` | Accounts created from seed can never go live until manually corrected. | Require valid ID format at account-creation time; don't seed placeholders. |
| 10 | **Working tree ≠ deployed code** | 9 uncommitted files revert post-June-25 improvements (Meta v18.0, localhost redirect, mirror-based leads). If committed, production regresses. | git working tree | User is testing locally on reverted code while production runs newer code → confusion. | Decide which version is correct; commit or discard intentionally. |
| 11 | **`ADOPTIMA_SCHEDULER_ENABLED` is a no-op** | Documented in `.env.example` but never read in any `.py` file. Scheduler always starts. | `.env.example:24`; absence in code | User thinks they can disable scheduler via env; they can't. | Either read the env in `start_scheduler()` or remove from docs. |
| 12 | **Scheduler lazy-start has no startup hook** | `lazy_start_scheduler` middleware starts scheduler on first request. If Railway restarts and no traffic comes, scheduler never starts → no metric refresh, no LSQ sync. | `app.py:54-67` | Stale data after deploy until first page load. | Use `@app.on_event("startup")` (or FastAPI lifespan) to start scheduler reliably. |
| 13 | **No `setval` self-heal** | After any manual ID insert, all sequences can desync. Only `leadsquared_leads_id_seq` was fixed manually today. Other tables (`accounts`, `users`, `rev_invoices`, etc.) are at risk. | `database.py` | Future bulk imports will break inserts. | Add a `reset_sequences()` function in `init_db()`. |
| 14 | **LSQ mirror staleness undetected** | `_fetch_lsq_leads` checks if mirror has ANY rows; if yes, uses mirror regardless of age. If sync has been failing for days, stale counts returned with no warning. | `dsu_data.py:215-221` | Reports show old lead counts silently. | Check `max(synced_at)`; if >6h old, log warning + fall back to direct API. |
| 15 | **DSI Table 1 had no date range selector (now fixed locally)** | DSI Table 1 was hardcoded to "yesterday" with no way to select a range. Fixed today via local edit to `mis.html`. | `mis.html:1095-1112` (now fixed) | Was unable to pull multi-day data for DSI. | Fixed. Ensure the fix is committed or preserved. |
| 16 | **Inconsistent SMTP defaults** | `onboarding_email.py` defaults to `smtp.office365.com`; `notification_dispatch.py` defaults to `smtp.gmail.com`. | `onboarding_email.py:16`; `notification_dispatch.py:47` | Email may fail in one path but work in another. | Unify to a single SMTP config source. |
| 17 | **JWT secret default is insecure** | `ADOPTIMA_JWT_SECRET` defaults to `"change-me-in-production"` if unset. | `auth.py:27` | If Railway var is missing, any JWT can be forged. | Fail fast in production if secret == default. |
| 18 | **Fernet master key default is insecure** | `ADOPTIMA_SECRET_KEY` defaults to `"adoptima-internal-secret-key-for-demo-only"`. If unset, all stored OAuth creds are encrypted with a known key. | `crypto.py:12` | If Railway var is missing, all OAuth credentials are effectively plaintext. | Fail fast in production. |
| 19 | **No graceful shutdown** | No `@app.on_event("shutdown")` → `stop_scheduler()` never called. Scheduler killed mid-job on Railway restart. | `app.py` | Interrupted sync/audit jobs leave DB in inconsistent state. | Add shutdown hook. |
| 20 | **Mantri route is all mock** | `routes/mantri.py:104-194` returns hardcoded sample data. Mantri config env vars exist but are never used. | `routes/mantri.py` | Mantri report is always "Sample data". | Implement live Salesforce/Meta calls or remove the view. |

---

## 13. Recommended Rule Book

### 13.1 Status hierarchy (clean)
1. **DISCONNECTED** — API call failed (auth/token/network). Red. No other badges matter.
2. **CRITICAL** — API works but: campaign paused, OR spend=0 at ≥80% of active window, OR CPA ≥1.5×target, OR pacing <20% at ≥80%.
3. **WARNING** — API works but: sync >3h old, OR spend=0 at ≥50%, OR CPA 1.2-1.5×target, OR 20+ clicks / 0 leads, OR micro-spend at ≥50%.
4. **GOOD** — API works, sync fresh, spend meaningful, impressions >0, CPA within target.
5. **NO DATA** — API works but returned 0 campaigns/metrics. Grey. Distinct from "zero spend on a running campaign".

### 13.2 Zero-data handling
- Distinguish "API returned empty" from "API failed". Show "No campaigns found" (grey) vs "API error" (red).
- Lead count 0 with spend>0 → show "0 leads" (yellow), NOT "No Leads" (which implies "can't compute CPL").
- Lead count 0 with spend=0 → show "0" (grey, no alarm).

### 13.3 Missing-data handling
- `null`/`None` from API → display "—" (em-dash), not "0" or "Rs 0".
- LSQ mirror stale (>6h) → fall back to direct API + log warning.
- Billing unavailable → "Billing: N/A" (grey), not "BILL ---".

### 13.4 Prepaid/postpaid logic
- **Prepaid** (Google): balance = total_budget − spend_since_budget_start. Show "BAL ₹X / ₹Y". Red if ≤0, yellow if <10%, neutral otherwise.
- **Postpaid** (Meta): show period spend (from insights, NOT lifetime amount_spent). Label "SPENT ₹X (this period)".
- **Unknown**: "Billing: N/A". Don't guess.

### 13.5 Ad health logic
- Use the campaign's actual schedule (from API `ad_schedule` field) for progress calculation. Default 9-21 if unavailable.
- If no schedule info, use 24h but recalibrate: warn at 60%, critical at 80%.
- "Today" preset should use today→today (not yesterday).
- Reset per-platform spend to 0 before accumulating for dual-platform accounts.

### 13.6 MIS validation
- Log unmapped campaigns to a `unmapped_campaigns` table for review.
- Validate Google customer ID format (`\d{3}-\d{3}-\d{4}`) at save time.
- Run `setval()` on all sequences in `init_db()`.
- Add `ALTER TABLE ADD COLUMN IF NOT EXISTS` for schema evolution.

### 13.7 Alert priority
1. DISCONNECTED (API down) — fix credentials.
2. CRITICAL (perf) — pause/fix campaign.
3. WARNING (perf) — review campaign.
4. LSQ mirror stale — trigger manual sync.
5. Billing low balance — add funds.
6. Zero leads with spend — check conversion tracking.

---

## 14. Final Output Format

This document IS the final output. It is structured as requested with tables in sections 5, 6, 10, 11, 12. No code was changed. No files were modified. No deployment was made.

**File:** `AGENT_RULE_BOOK.md` (this file) at repo root.

**Next step:** Review this rule book, confirm which assumptions are intentional, then I can implement fixes one-by-one with your approval.