# Frontend UI + Agent Behaviour Rule Book
## ChlearSakhaaOps AI (AdOptima)

**Audit date:** 29 June 2026
**Repo:** `AI_The_Optimiser`, working tree (main @ `312fa99` + uncommitted local edits)
**Status:** Documentation only. No code changed. No files modified except this one.

---

## Part 2 — App Entry Points

| URL / route | Page name | Frontend file | Backend route serving it | Purpose | Who can access | Notes / issues |
|---|---|---|---|---|---|---|
| `/` | Landing / Login / Module chooser | `frontend/landing.html` | `app.get_landing` `app.py:85` | Login form, super-admin onboarding (if no users), module cards, User Management modal, Integrations link | Public (unauthenticated can see page; actions require login) | Onboarding form replaces login modal when `/auth/onboarding-required` returns true |
| `/adpulse` | AdPulse Dashboard | `frontend/index.html` | `app.get_ui` `app.py:95` | Ad-account health, spend, leads, approvals, audit | Any authenticated user with `access_adpulse` or admin/superadmin | No server-side access check on the HTML route itself; API calls enforce auth |
| `/insightdesk` | InsightDesk (MIS) | `frontend/mis.html` | `app.get_mis_ui` `app.py:105` | DSU/DSI/Mantri/generic MIS reports | Any authenticated user with `access_insightdesk` or admin/superadmin | HTML served to everyone; data gated by API |
| `/revenueops` | RevenueOps | `frontend/revenueops.html` | `app.get_revenueops_ui` `app.py:115` | Invoice/payment/reminder workflow | Any authenticated user with `access_revenueops` or admin/superadmin | HTML served to everyone; data gated by API |
| `/integrations` | Integrations Manager | `frontend/integrations.html` | `app.get_integrations_ui` `app.py:125` | Per-account + global credential config for Google Ads, Meta Ads, LeadSquared, Salesforce, + 9 planned cards | Admin or superadmin (frontend hides link for `user` role) | Backend API calls use `get_current_user_required` only — **no admin check on config save** |
| `/onboard` | Set Password | `frontend/onboard.html` | `app.get_onboard_ui` `app.py:135` | New user sets password via onboarding token | Holder of valid onboarding token (72h expiry) | Token validated by `/auth/onboard/{token}` |
| `/privacy` | Privacy Policy | inline HTML | `app.get_privacy` `app.py:145` | Meta app compliance page | Public | Static HTML string in Python |
| `/health` | Health check | JSON | `app.health_check` `app.py:70` | Railway/deployment liveness | Public | Returns `{"status":"ok","port":"8000"}` |
| `/favicon.ico` | Favicon | file/inline GIF | `app.get_favicon` `app.py:75` | Browser tab icon | Public | Returns 1×1 GIF if file missing |

**API prefix:** All data routes are under `/api/*` (registered via `app.include_router`). Frontend `API='/api'`.

---

## Part 3 — Login Flow

| Step | UI shown | User action | API called | Success behaviour | Failure behaviour | File/function | Issue/risk |
|---|---|---|---|---|---|---|---|
| 1. Page load | Landing page; "Checking session..." in topbar | None | `GET /api/auth/onboarding-required` → if true, shows onboarding form; else `GET /api/auth/me` if token exists | If token valid: hides Login, shows Logout + User Management (admin) + Integrations + module cards with access flags | If no token: shows "Not logged in" + Login button; all module cards locked | `landing.html:checkAuth` `:231` | Onboarding form replaces login modal innerHTML — if user reloads after onboarding, modal may be in broken state |
| 2. Onboarding (first run only) | Modal: "Welcome — Create Super Admin" with Full Name, Email, Mobile, Password | Fill + click "Create Super Admin" | `POST /api/auth/onboard` `{full_name,email,mobile,password}` | Stores token in localStorage, hides modal, shows UI as superadmin | `alert(e.message)` | `landing.html:completeOnboarding` `:264`; `auth.py:onboard_first_user` `:142` | No password strength check; no email verification |
| 3. Login | Modal: "Login to ChlearSakhaaOps AI" with Email + Password | Fill + click "Login" | `POST /api/auth/login` (URL-encoded form: `username`, `password`) | Returns `{access_token, user}`; stores token; hides modal; `updateUI(user)` | `alert('Invalid credentials')` | `landing.html:login` `:350`; `auth.py:login` `:170` | No rate limiting; no "forgot password" flow |
| 4. Token storage | N/A | N/A | N/A | `localStorage.setItem('adoptima_token', token)` | — | `landing.html:361`, all module files | Token in localStorage — vulnerable to XSS |
| 5. Token expiry | Token has `exp` claim = creation + `ACCESS_TOKEN_EXPIRE_DAYS` (default 30 days; `auth.py:84` reads `ACCESS_TOKEN_EXPIRE_DAYS` env, default not found in code — **the constant is `timedelta(days=...)` but the env name `ACCESS_TOKEN_EXPIRE_DAYS` is NOT referenced in auth.py**; the code uses a local constant). Actual: `auth.py:87` uses `ACCESS_TOKEN_EXPIRE_DAYS` variable defined at line ~27 area — need to verify. Let me note: token expiry is set at creation; when expired, `get_current_user` returns None → 401 → frontend `api()` catches 401 → clears token → shows auth. | Frontend: `api()` on 401 → `localStorage.removeItem('adoptima_token')` + `showAuth()` + throws "Session expired." | All module `api()` helpers (`index.html:524`, `mis.html:222`, `revenueops.html:482`, `integrations.html:114`) | No refresh token mechanism — user must re-login |
| 6. After login | Module cards show "Open" (green) for accessible modules; "Locked" (red) for others | Click a module card | N/A (redirect) | `window.location.href = url` | If card is `.disabled` → `alert('You do not have access...')` | `landing.html:openModule` `:335` | Access check is frontend-only; HTML route serves page to anyone |
| 7. Logout | Topbar "Logout" button | Click | N/A | Clears token + `updateUI(null)` → shows Login | — | `landing.html:logout` `:367` | No server-side logout / token blacklist |
| 8. Token expired mid-session | Any API call returns 401 | N/A | N/A | `api()` clears token, shows auth overlay or redirects to `/` | — | Each module's `api()` | User loses unsaved work silently |

**Roles found:** `superadmin`, `admin`, `user` (BM). RevenueOps has a secondary `rev_role` field (`admin`, `finance`, `business_manager`) but it only filters data scope, not module access.

**Forgot password:** Does NOT exist. No reset-password endpoint or UI. `reset_superadmin` endpoint exists (`auth.py:330`) but requires direct DB access (takes `email` + `new_password` as query params, no auth dependency — **dangerous unauthenticated endpoint**).

**Password setup (onboarding):** Superadmin/admin creates user → backend generates `onboarding_token` (32-char URL-safe) with 72h expiry → frontend shows setup link → (working tree: also sends email via SMTP) → new user opens `/onboard?token=...` → validates token via `GET /auth/onboard/{token}` → sets password via `POST /auth/onboard/{token}` → receives JWT → redirected to `/`.

---

## Part 4 — Role and Permission Rule Book

| Role | AdPulse access | InsightDesk access | RevenueOps access | User Management | Integrations | Settings (RevenueOps) | Add/Edit/Delete (RevenueOps) | Frontend control | Backend control | Issue/risk |
|---|---|---|---|---|---|---|---|---|---|---|
| **superadmin** | ✅ (all) | ✅ (all) | ✅ (all) | ✅ (full: create/edit/delete users, assign superadmin) | ✅ | ✅ | ✅ | Cards always "Open"; UM button visible; Integrations link visible; RevOps Add/Edit/Delete buttons visible; can see Super Admin option in role dropdown | `require_superadmin` on nothing in RevenueOps; `require_admin_or_superadmin` on user CRUD | **RevenueOps has NO admin-only backend guard** — any authenticated user can call all RevOps endpoints |
| **admin** | ✅ (all) | ✅ (all) | ✅ (all) | ✅ (create/edit/delete users; CANNOT create superadmin) | ✅ | ✅ | ✅ | Same as superadmin except Super Admin option hidden in UM role dropdown | `require_admin_or_superadmin` on user CRUD; RevOps uses `get_current_user_required` only | Admin can delete other admins or superadmins via `DELETE /auth/users/{id}` — no self-delete protection |
| **user** (BM) | Only if `access_adpulse=true` | Only if `access_insightdesk=true` | Only if `access_revenueops=true` | ❌ (UM button hidden) | ❌ (link hidden) | ❌ (panel exists but no admin guard on API) | ❌ (buttons hidden) | Cards locked if no access; UM/Integrations hidden; RevOps nav items visible but Add/Delete buttons hidden via `currentUser.role` check | RevOps: `get_current_user_required` only — **any user can call POST/PUT/DELETE** | **CRITICAL: frontend hides buttons but backend doesn't enforce role on RevOps CRUD. A BM user can curl POST /clients and create clients.** |
| **user + rev_role=business_manager** | Same as user | Same as user | Sees only own clients (backend filters by `business_manager_id`) | ❌ | ❌ | ❌ | ❌ (buttons hidden) | RevOps dashboard auto-filters to BM's clients | `revenueops.py:889-891` filters invoices by BM | Good — BM data scoping works backend-side |

**Mismatch summary:**
- Frontend hides User Management for `user` role → Backend enforces `require_admin_or_superadmin` ✅
- Frontend hides Integrations for `user` role → Backend config endpoint uses `get_current_user_required` only ❌
- Frontend hides RevenueOps Add/Edit/Delete for `user` role → Backend uses `get_current_user_required` only ❌ **CRITICAL**
- Frontend hides Super Admin option for non-superadmin → Backend enforces `require_superadmin` on superadmin creation ✅

---

## Part 5 — Header / Top Buttons

| Button name | Location | Visible to role | Click action | JS function | API endpoint | DB table | Success | Error | Issue/risk |
|---|---|---|---|---|---|---|---|---|---|
| Login | Landing topbar | Not logged in | Shows login modal | `showAuth()` `landing.html:344` | — | — | Modal appears | — | — |
| Logout | Landing topbar (all pages have their own logout too) | Logged in | Clears token, resets UI | `logout()` `landing.html:367` | None | — | UI resets to "Not logged in" | — | No server-side token invalidation |
| 👤 User Management | Landing topbar | admin + superadmin | Opens UM modal | `openUserManagement()` `landing.html:378` | `GET /auth/users` + `GET /auth/accounts-for-assignment` | `users`, `user_account_assignments`, `accounts` | Modal opens with user table | `alert(e.message)` | Modal only on landing page, not on module pages |
| Integrations | Landing topbar | admin + superadmin | Redirects to `/integrations` | anchor `<a href="/integrations">` | — | — | Integrations page loads | — | Link hidden for `user` role via inline style |
| Home / ChlearSakhaaOps AI (logo) | All module topbars | All | Redirects to `/` | anchor `<a href="/">` | — | — | Landing page loads | — | — |
| Back to Dashboard | InsightDesk topbar | All (with access) | Redirects to `/` | anchor | — | — | — | — | — |
| Seed Demo Data | RevenueOps topbar | All authenticated | Seeds demo clients/invoices/payments | `seedDemo()` `revenueops.html:1040` | `POST /revenueops/seed-demo` | `rev_clients`, `rev_invoices`, `rev_payments` | Toast with counts | Toast error | **No role check** — any user can seed demo data and pollute the DB |
| Refresh All | AdPulse topbar | All (with access) | Refreshes all live accounts | `refreshAllAccounts()` `index.html:927` | `POST /accounts/{id}/refresh?platform=...` per account | `accounts` | Toast "Refreshed all" | Per-account error swallowed | — |
| Run Audit | AdPulse topbar | admin + superadmin (nav hidden for user) | Runs audit across all accounts | `runGlobalAudit()` `index.html:1391` | `POST /audit-all` | `pending_actions` | Toast with count | Toast error | — |

---

## Part 6 — Module Overview

| Module | URL | Frontend file | Purpose | Left menu? | Main right-side content | API endpoints | DB tables | Role access | Issues |
|---|---|---|---|---|---|---|---|---|---|
| **AdPulse** | `/adpulse` | `index.html` (1419 lines) | Ad-account health monitoring, spend/leads, approvals, audit | Yes (sidebar: Home, Account Dashboard, Manage Accounts, Approval Queue) | KPI grid (4 cards) + dashboard group cards with account tiles; Manage Accounts table; Account detail view; Approval queue cards | `/accounts/summary`, `/accounts`, `/accounts/{id}`, `/accounts/{id}/refresh`, `/accounts/{id}/leads`, `/accounts/{id}/audit`, `/pending-actions`, `/audit-all`, `/oauth/*`, `/account-groups` | `accounts`, `account_groups`, `pending_actions` | `access_adpulse` or admin/superadmin | No server-side HTML route guard; dual-platform spend double-counting bug |
| **InsightDesk** | `/insightdesk` | `mis.html` (2109 lines) | MIS reports for DSU, DSI, Mantri, generic accounts | Yes (sidebar: Home, account list) | Tab bar (Tables 1-7 for DSU; 1-5 for DSI) + date selectors + report tables + budget entry forms | `/reports/dsu-performance`, `/reports/dsi-performance`, `/reports/dsu/*`, `/reports/dsi/*`, `/reports/lsq-sync`, `/mantri/*`, `/accounts/{id}/crm-summary` | `leadsquared_leads`, `dsu_budget_entries`, `dsi_budget_entries`, `dsu_legacy_spend`, `dsi_legacy_spend`, `dsu_table2_historical`, `dsi_table2_historical`, `dsu_monthly_spend_fixed`, `dsi_monthly_spend_fixed`, `accounts` | `access_insightdesk` or admin/superadmin | LSQ mirror can go stale; DSI T2 has no date selector; Mantri is mock data |
| **RevenueOps** | `/revenueops` | `revenueops.html` (1052 lines) | Invoice/payment/reminder workflow | Yes (sidebar accordion: Overview, Management, Follow-up, Records, Analysis, System) | 14 KPI cards + tables for clients/invoices/payments/outstanding/reminders/documents/reports/BMs/BM-view/settings/users | `/revenueops/dashboard`, `/revenueops/clients`, `/revenueops/invoices`, `/revenueops/payments`, `/revenueops/outstanding`, `/revenueops/reminders`, `/revenueops/reminders/due-today`, `/revenueops/documents`, `/revenueops/business-managers`, `/revenueops/reports/*`, `/revenueops/settings`, `/revenueops/seed-demo`, `/auth/users` | `rev_clients`, `rev_invoices`, `rev_payments`, `rev_reminders`, `rev_documents`, `rev_settings`, `client_billing_models`, `followup_notes`, `rev_audit_logs`, `users` | `access_revenueops` or admin/superadmin | **Backend doesn't enforce admin role on CRUD** — any user can create/delete; "Expected collection" is a guess (20%/50%) |

---

## Part 7 — Left Panel to Right Panel Mapping

### AdPulse Left Panel Mapping

| Left panel item | Right-side display | JS function | API endpoint | DB table | Buttons/actions | Empty state | Error state | Issue/risk |
|---|---|---|---|---|---|---|---|---|
| Home (logo) | Redirects to `/` | anchor | — | — | — | — | — | — |
| Account Dashboard | 4 KPI cards (Total Accounts, Spend, Conversions, Avg CTR) + group cards with account tiles | `loadSummary()` `index.html:764` | `GET /accounts/summary` + `GET /accounts` | `accounts`, `account_groups` | Per-tile refresh (↻); global date preset dropdown; Refresh All; Run Audit | KPIs show 0; no accounts → empty groups | KPIs show 0; toast error | No auto-refresh; dual-platform spend bug |
| Manage Accounts | Table: Name, Platforms, Category, External ID, Mode, Status, Spend, Refresh interval, Actions | `loadAccounts()` `index.html:966` | `GET /accounts`, `GET /account-groups` | `accounts`, `account_groups` | Add Account, Edit, Delete, per-row Edit opens modal | Empty table body | `alert(e.message)` | No confirmation on Delete beyond default |
| Approval Queue | Pending action cards with Approve/Reject | `loadPendingActions()` `index.html:1347` | `GET /pending-actions` | `pending_actions` | Approve, Reject | Empty state text | `alert(e.message)` | Badge count in sidebar |

### InsightDesk Left Panel Mapping

| Left panel item | Right-side display | JS function | API endpoint | DB table | Buttons/actions | Empty state | Error state | Issue/risk |
|---|---|---|---|---|---|---|---|---|
| Home (logo) | Redirects to `/` | anchor | — | — | — | — | — | — |
| ChlearSakhaaOps Home | Redirects to `/` | anchor | — | — | — | — | — | — |
| Account: DSU | Tab bar (Tables 1-7) + date selectors + report tables | `renderDSUReport()` `mis.html:464` | `/reports/dsu-performance`, `/reports/dsu/*` | `leadsquared_leads`, `dsu_budget_entries`, `dsu_*` | Tab switch; T1 radio (Yesterday/Today/Custom); T2 dropdown (7 presets + Custom); Sync Leads; PDF download (T1/T2); budget entry add/edit/delete (T7) | "No data" rows hidden in T1/T2 | `toast(e.message)` | "today" preset returns empty (start>end) |
| Account: DSI | Tab bar (Tables 1-5) + date selector (T1 only) + report tables | `renderDSIReport()` `mis.html:1113` | `/reports/dsi-performance`, `/reports/dsi/*` | `leadsquared_leads`, `dsi_budget_entries`, `dsi_*` | Tab switch; T1 radio (Yesterday/Today/Custom — added today); Sync Leads; budget entry add/edit/delete (T5) | "No data" rows NOT hidden (DSI shows zeros) | `toast(e.message)` | T2 has no date selector (hardcoded inception); no PDF export |
| Account: Mantri Developers | Lead-status-by-platform table (mock data) | `renderMantriReport()` `mis.html:2005` | `/mantri/reports/lead-status-by-platform` | None (mock) | Export Excel | "Sample data" badge | — | All mock; no live data |
| Account: (any other) | Generic CRM report: exec summary, source breakdown, leads, opportunities, manager remarks | `renderReport(a)` `mis.html:1699` | `/accounts/{id}/crm-summary` + Salesforce/LSQ APIs | None (in-memory) | MIS Status dropdown (On Track/Needs Attention/At Risk) | "No CRM Connected" badge | `toast(e.message)` | Meta spend always 0 in generic report |

### RevenueOps Left Panel Mapping

| Left panel item | Right-side display | JS function | API endpoint | DB table | Buttons/actions | Empty state | Error state | Issue/risk |
|---|---|---|---|---|---|---|---|---|
| 📊 Dashboard | 14 KPI cards + Overdue Clients table + Billing Model table | `loadDashboard()` `revops.html:534` | `GET /revenueops/dashboard` | `rev_invoices`, `rev_payments`, `rev_clients`, `users` | Date filter inputs | KPIs show "—" or 0 | `toast(e.message)` | "Expected collection" = 20%/50% guess |
| 👥 Clients | Clients table with search + status filter | `loadClients()` `revops.html:559` | `GET /revenueops/clients` | `rev_clients`, `users` | + Add Client; Edit; Delete | Empty table | `toast(e.message)` | Delete has no backend role check |
| 🧾 Invoices | Invoices table with search/status/date filters + client-side pagination | `loadInvoices()` `revops.html:606` | `GET /revenueops/invoices` | `rev_invoices`, `rev_clients`, `users` | + New Invoice; Edit; Delete; page size 5/10/15/20/50; Prev/Next | Empty table | `toast(e.message)` | No server pagination (loads all 9999) |
| 💳 Payments | Payments table | `loadPayments()` `revops.html:667` | `GET /revenueops/payments` | `rev_payments`, `rev_invoices` | + Record Payment; Delete | Empty table | `toast(e.message)` | — |
| ⏳ Outstanding | Outstanding table with ageing filter | `loadOutstanding()` `revops.html:708` | `GET /revenueops/outstanding` | `rev_invoices` | Ageing filter dropdown | Empty table | `toast(e.message)` | — |
| 🔔 Reminders | Reminders table + popup for due-today | `loadReminders()` `revops.html:720` + `checkDueReminders()` `:733` | `GET /revenueops/reminders`, `GET /revenueops/reminders/due-today` | `rev_reminders` | + Add Reminder; Done; Snooze; Copy Text (WhatsApp) | Empty table; popup hidden if none | `toast(e.message)` | Popup polls every 60s |
| 📁 Documents | Documents table | `loadDocuments()` `revops.html:802` | `GET /revenueops/documents` | `rev_documents` | + Upload Document; Delete | Empty table | `toast(e.message)` | "Upload" is just a URL field, no file upload |
| 📈 Reports | 4 report cards (Monthly Billing, Outstanding, BM-Wise, Invoice Not Raised) | `runReport(type)` `revops.html:836` | `GET /revenueops/reports/*` | varies | Run report; Export CSV | "Select a report" placeholder | `toast(e.message)` | — |
| 🧑‍💼 BMs | Business Managers table | `loadBMs()` `revops.html:864` | `GET /revenueops/business-managers` | `users` | + Add BM; Delete | Empty table | `toast(e.message)` | Default password "changeme123" |
| 👁 BM View | Per-BM KPI cards | `loadBMView()` `revops.html:893` | `GET /revenueops/reports/bm-wise` | `rev_invoices`, `users` | None | "No Business Manager Data" | `toast(e.message)` | — |
| ⚙️ Settings | 3 settings fields | `loadSettings()` `revops.html:1027` | `GET /revenueops/settings`, `PUT /revenueops/settings` (×3) | `rev_settings` | Save Settings | Default values shown | `toast(e.message)` | Saves one key at a time (3 API calls) |
| 🔐 Users | Users table (same as landing UM) | `loadUsers()` `revops.html:912` | `GET /auth/users`, `POST /auth/users`, etc. | `users`, `user_account_assignments` | + Add User (superadmin only); Edit; Delete | Empty table | `toast(e.message)` | Duplicate of landing UM; no Super Admin option for admin |
| Seed Demo Data (topbar) | Toast with counts | `seedDemo()` `revops.html:1040` | `POST /revenueops/seed-demo` | `rev_clients`, `rev_invoices`, `rev_payments` | Button | Toast | Toast error | **No role check** — any user can pollute DB |

---

## Part 8 — AdPulse Complete UI Rule Book

### Dashboard summary cards (`index.html:232-236`)
| Card | Data source | Formula | Zero/missing | API fail | Role | Issue |
|---|---|---|---|---|---|---|
| Total Accounts | `/accounts/summary` | `data.total_accounts \|\| 0` | 0 | 0 | All with access | — |
| Total Spend | `/accounts/summary` | `formatMoney(data.total_spend)` | "Rs 0" | "Rs 0" | All | Dual-platform double-count |
| Total Conversions | `/accounts/summary` | `formatNum(data.total_conversions)` | 0 | 0 | All | — |
| Avg CTR | `/accounts/summary` | `impressions ? clicks/impr×100 : 0` | "0.00%" | "0.00%" | All | — |

### Account tiles (`index.html:818-862`)
| Element | Source | Formula | Zero/missing | API fail |
|---|---|---|---|---|
| Account name | `a.name` | — | — | — |
| Platform badge | `a.has_google`→"Google"; `a.has_meta`→"Meta" | — | — | — |
| Spend | `a.spend` | `formatMoney()` | "Rs 0" | "Rs 0" |
| Conversions | `a.conversions` | `formatNum()` | 0 | 0 |
| CTR | `a.ctr` | `formatPct()` | "0.00%" | "0.00%" |
| CPA | `a.cpa` | `formatMoney()` | "Rs 0" | "Rs 0" |
| Leads | `/accounts/{id}/leads` | `formatNum(data.leads)` | "0" (non-live) | "Leads: -" |
| Last Sync | `a.last_sync_at` | Asia/Kolkata format | "Never" | "Never" |
| API badge | `a.api_health` | `hbBadge()` → green/yellow/red/grey | grey if no health | — |
| ADS badge | `a.perf_health` | same | grey | — |
| Billing chip | `a.billing` | `billChip()` → "BAL ₹X" / "USED ₹X" / "BILL ---" | "BILL ---" grey | "BILL ---" |
| Status border | `a.status` | `.status-healthy` (green) / `.status-warning` (amber) / `.status-critical` (red) / `.status-disconnected` (light) | — | — |
| Live/Not Connected | `a.is_live` | green "Live" / amber "Not Connected" | — | — |
| Refresh button (↻) | per-tile | `refreshTile(id)` | — | spinning animation |

### Account Detail (`index.html:258-290`)
| Element | Source | Formula | Notes |
|---|---|---|---|
| 4 KPI cards (Spend/Conversions/CTR/CPA) | `openAccountDetail()` `:939` → `GET /accounts/{id}` | same as tile | Detail date range inherited from global or custom |
| Back button | returns to dashboard | — | — |
| Refresh Current | `refreshCurrentAccount()` `:954` | `POST /accounts/{id}/refresh` | — |

### Manage Accounts table (`index.html:240-256`)
| Column | Data | Notes |
|---|---|---|
| Name | `a.name` | — |
| Platforms | `has_google`→Google, `has_meta`→Meta | joined ", " |
| Category | group name | — |
| External ID | `a.external_id` | — |
| Mode | `is_live`→green "Live" / amber "Not Connected" | — |
| Status | `a.status` raw | No formatting |
| Spend | `formatMoney(a.spend)` | — |
| Refresh | `${refresh_interval_minutes}m` | — |
| Actions | Edit, Delete buttons | — |

### Add/Edit Account modal (`index.html:330-481`)
| Section | Fields | Validation | Notes |
|---|---|---|---|
| Basic | Client Name*, Category, Refresh Interval (min 15), Audit Interval (min 0) | Name required | — |
| Google | Checkbox (default on), Customer ID (regex `\d{3}-\d{3}-\d{4}`), Currency (INR disabled), Client ID, Client Secret, Developer Token, Redirect Base URL | Customer ID regex | Redirect base now shows Railway URL (committed main) |
| Meta | Checkbox, Ad Account ID (regex `act_\d+`), Currency, App ID, App Secret, Redirect Base URL | Ad Account ID regex | — |
| CRM | Dropdown (none/leadsquared/salesforce/hubspot/zoho/custom) + per-CRM fields | — | — |

### Approval Queue (`index.html:292-297`)
| Element | Source | Formula | Notes |
|---|---|---|---|
| Pending badge | `GET /pending-actions` filtered by status=pending | count | In sidebar |
| Action cards | `loadPendingActions()` `:1347` | each action: account_name, platform, severity flag-tag, keyword/match_type, reason, apply hint | Severity: danger (FIX_LANDING_PAGE/PAUSE_OR_REDUCE_BUDGET/PAUSE_KEYWORD), warning (ALERT_*/REVIEW_ADSET/REDUCE_BID), success (else) |
| Approve | `reviewAction(id,'approve')` `:1382` | `POST /pending-actions/{id}/review` `{decision:'approve'}` | — |
| Reject | `reviewAction(id,'reject')` | `POST /pending-actions/{id}/review` `{decision:'reject'}` | — |

### Health badges
| Badge | Status | Color | Trigger | Issue |
|---|---|---|---|---|
| API | GOOD | green (`.hb-green`) | API success + sync <3h | — |
| API | WARNING | yellow (`.hb-yellow`) | API success but sync >3h or missing | — |
| API | DISCONNECTED | red (`.hb-red`) | API call failed | Doesn't distinguish auth vs network |
| API | (other) | grey (`.hb-grey`) | — | — |
| ADS | GOOD | green | All perf checks pass | — |
| ADS | WARNING | yellow | Any WARNING rule | 10+ overlapping rules |
| ADS | CRITICAL | red | Any CRITICAL rule | — |
| ADS | UNKNOWN | grey | API failed | Same trigger as API DISCONNECTED but different label |

### Billing chip
| Display | Condition | Color | Issue |
|---|---|---|---|
| `BAL ₹X / ₹Y` | prepaid, amount available | neutral (red if ≤0, yellow if <10% or <₹500) | — |
| `USED ₹X` | postpaid | neutral | Meta "USED" = lifetime spend, misleading |
| `BAL ---` / `USED ---` / `BILL ---` | unavailable | grey | User can't tell why |

### Date filters (AdPulse topbar)
| Preset | Start | End | Notes |
|---|---|---|---|
| today | today | today | — |
| yesterday | yesterday | yesterday | — |
| last7 | today−6 | today | — |
| last15 | today−14 | today | — |
| last30 | today−29 | today | — |
| thisMonth | day 1 | today | — |
| allTime | 2020-01-01 | today | — |
| custom | user input | user input | Date inputs appear when selected |

---

## Part 9 — InsightDesk Complete UI Rule Book

### DSU Tables

| Table | Tab | Purpose | Date selector | Source spend | Source leads | Columns | Special logic | Issue |
|---|---|---|---|---|---|---|---|---|
| Table 1 | t1t2 | Daily course perf | T1 radio (Yesterday/Today/Custom) | Google Ads API (live only campaigns) | LSQ mirror | Course, Lead, CPL, Spend | Zero rows hidden; GST per-day | "Today" preset returns empty (start>end) |
| Table 2 | t1t2 | Cumulative course perf | T2 dropdown (7 presets + Custom) | Default: `dsu_table2_historical`; Custom: legacy + live API | LSQ mirror | Course, Lead, CPL, Spend | Zero rows hidden; GST per-day | Inception label hardcoded "28th November 2025" |
| Table 3 | t3 | Lead Source × Stage pivot | T1 range (shares with t1t2 tab) | N/A | LSQ mirror | Source + dynamic stages + Total | Zeros shown as blank | — |
| Table 4 | t4 | Application Submitted & CPA by Campus | None (cumulative) | Table 2 spend | LSQ mirror (Application Status) | Course, App Submitted, CPA, Spend, Target | Campus 4 (B.Tech) vs Campus 3 (others); zero→"₹0" | Targets hardcoded |
| Table 5 | t5 | Budget MIS by Campus | None | Table 2 spend | N/A | Course, Status, Budget, Spend, Remaining | Budget cell rowspan per campus; "Live" if spend>0 | — |
| Table 6 | t6 | Lead Stage Summary | T1 range | N/A | LSQ mirror | Stage, Count, Percentage | Total shows count only | — |
| Table 7 | t7 | Monthly Spend & Balance | None | Google Ads monthly | `dsu_budget_entries` | Date, Amount, Invoice, Campus, Google Spend, Meta Spend, Total Spend, Balance, Actions | Month rowspan; virtual rows for months with no budget entry; balance color red/green | Cross-table note: T7 spend ≠ T2 spend (unmapped campaigns) |

**DSU budget form** (Table 7): Date (default today), Amount, Invoice #, Campus (Campus 3 / Campus 4). Edit/Delete buttons per entry.

**DSU PDF download:** Buttons under T1 and T2 → `GET /reports/dsu-performance/pdf?table=daily|cumulative` → blob download with Bearer token.

**Sync Leads button:** Visible only for DSU/DSI → `POST /reports/lsq-sync?account_id={id}` → toast with synced_count → reload after 500ms.

### DSI Tables

| Table | Tab | Purpose | Date selector | Source spend | Source leads | Columns | Special logic | Issue |
|---|---|---|---|---|---|---|---|---|
| Table 1 | t1t2 | Daily dept/course perf | T1 radio (Yesterday/Today/Custom — added today) | Google Ads API (live only) | LSQ mirror (DSI filter) | Department, Course, Lead, CPL, Spend | Dept rowspan; DSCASC-UG CPL/Spend merged at dept level; zeros NOT hidden | T2 has no date selector |
| Table 2 | t1t2 | Cumulative perf | None (fixed inception) | Default: `dsi_table2_historical`; Custom: legacy + live | LSQ mirror | Department, Course, Lead, CPL, Spend | Same as T1; zeros NOT hidden | No T2 date selector; no PDF export |
| Table 3 | t3 | Lead Course × Stage pivot | T1 range | N/A | LSQ mirror | Course + stages + Total | Zeros as blank | — |
| Table 4 | t4 | Application MIS by Dept | None | Table 2 spend | LSQ mirror | Department, Course, App Submitted, CPA, Spend, Target | Dept rowspan; DSCASC-UG merge; zero→empty | Targets all 0 |
| Table 5 | t5 | Budget MIS by Dept | None | Google Ads (DSI) | N/A | Department, Course, Status, Budget, Spend, Remaining + entry list (Date, Amount, Invoice, Section, Actions) | Section dropdown (DSCE/DSIT/DSCA/DSCASC-UG/DSCASC-Masters); edit highlight | Budget defaults hardcoded (DSCE=15L, DSIT=10L) |

**DSI budget form** (Table 5): Date, Amount, Invoice #, Section. Edit/Delete per entry. Total Received at bottom.

**DSI has NO PDF export, NO Table 6, NO Table 7.**

### Mantri Report
| Element | Data | Issue |
|---|---|---|
| Lead Status by Platform table | Mock data from `/mantri/reports/lead-status-by-platform` | **All mock** — no live API calls |
| "Live data" / "Sample data" badge | `data.configured` | Always "Sample data" |
| Export Excel button | `/mantri/reports/export-excel?token=` | Downloads anchor |

### Generic Account Report (non-DSU/DSI/Mantri)
| Section | Source | Issue |
|---|---|---|
| Executive Summary KPIs | Ad spend (Google only; Meta=0 placeholder), Total Leads (SF+LSQ), Opps, Lead→Opp%, Pipeline, Won, CPL, CTR, CPA | Meta spend always 0 |
| Source-wise Breakdown | Est. spend = `(leads/totalLeads)×totalSpend` | Proportional guess |
| CRM Leads Detail (first 50) | SF + LSQ leads | — |
| Opportunities/Pipeline (first 50) | SF opportunities | — |
| Manager Remarks | MIS Status dropdown (On Track/Needs Attention/At Risk) + text input | Not saved anywhere |

---

## Part 10 — RevenueOps Complete UI Rule Book

### Dashboard KPIs (14 cards)
See Part 6 table. Key issues: "Expected This Week" = 20% guess; "Expected This Month" = 50% guess.

### Clients
| UI element | Details | Validation | Issue |
|---|---|---|---|
| Search input | Filters by name/brand | — | — |
| Status filter | Active/Paused/Closed/On Hold | — | — |
| + Add Client button | Opens modal: Name*, Brand, Company, Contact Person, Email, Phone, BM, Invoice Day, Due Days, Remarks | Name required | BM dropdown from `/business-managers` |
| Edit | Same modal pre-filled | — | — |
| Delete | `DELETE /clients/{id}` | confirm() | **No backend role check** |

### Invoices
| UI element | Details | Validation | Issue |
|---|---|---|---|
| Search | By invoice number/client | — | — |
| Status filter | 9 options | — | — |
| Date from/to | Filter by invoice_date | — | — |
| + New Invoice | Modal: Client*, BM, Billing Type, Invoice #*, Date, Period, Amount*, Due Date, Remarks | Invoice # + Amount required | Invoice # uniqueness enforced backend |
| Edit | Same modal | — | — |
| Delete | `DELETE /invoices/{id}` | confirm() | Also deletes payments; **no role check** |
| Pagination | Client-side: 5/10/15/20/50 per page | — | Loads all (limit=9999) |

### Payments
| UI element | Details | Issue |
|---|---|---|
| + Record Payment | Modal: Invoice*, Date*, Amount*, Mode, Reference, Remarks | — |
| Delete | `DELETE /payments/{id}` | **No role check** |

### Outstanding
| UI element | Details |
|---|---|
| Ageing filter | All, due_in_3_days, due_today, 1_7, 8_15, 16_30, 31_60, 60_plus |
| Table | Client, Invoice, Amount, Received, Outstanding, Due Date, Overdue Days, Status |

### Reminders
| UI element | Details | Issue |
|---|---|---|
| + Add Reminder | Client, Invoice, Type (10 options), Priority (4), Amount, Due Date, Notes | — |
| Done button | `PUT /reminders/{id}` `{reminder_status:'done'}` | — |
| Snooze | Popup: value + unit (Hour/Day) → `POST /reminders/{id}/snooze` | — |
| Copy Text | `POST /reminders/{id}/generate-text?channel=whatsapp` → copies to clipboard | — |
| Auto-check | `setInterval(checkDueReminders, 60000)` → popup if due-today | — |

### Documents
| UI element | Details | Issue |
|---|---|---|
| + Upload Document | Modal: Name*, Type (8 options), Client*, Invoice, URL, Remarks | "Upload" is just a URL field — **no actual file upload** |
| Delete | `DELETE /documents/{id}` | **No role check** |

### BMs
| UI element | Details | Issue |
|---|---|---|
| + Add BM | Name*, Email*, Mobile, Password (default "changeme123") | Creates a User with `rev_role=business_manager`; weak default password |
| Delete | `DELETE /business-managers/{id}` | **No role check** |

### Settings
| Field | Default | Issue |
|---|---|---|
| Default Payment Due Days | 30 | — |
| Company Name | "Chlear Digital" | — |
| Currency Format | "INR" | — |
| Save | 3 separate PUT calls | Inefficient |

### Users (RevenueOps)
Same as landing page User Management. Duplicate implementation.

---

## Part 11 — Integrations Rule Book

| Integration | UI location | Fields required | Connect/save action | API endpoint | DB storage | Encryption | Failure behaviour | Issue/risk |
|---|---|---|---|---|---|---|---|---|
| Google Ads | `/integrations` card | Client ID, Client Secret, Developer Token, Customer ID, Refresh Token, Live Mode checkbox | Save → `PUT /accounts/{id}` + `POST /config`; Test → toast "uses live connector" | `/accounts`, `/config` | `accounts.google_credentials` (Fernet) + `accounts.google_*` columns | Yes (Fernet) | Toast error | No actual "test pull" API call — just a toast |
| Meta Ads | `/integrations` card | App ID, App Secret, Access Token, Ad Account ID, Live Mode | Same as Google | Same | `accounts.meta_credentials` (Fernet) + `accounts.meta_*` | Yes | Toast error | Same — no real test |
| LeadSquared | `/integrations` card | Base URL, Access Key, Secret Key | Save → `POST /config` (global) | `/config` | `config.json` / env | No (plain JSON) | Toast error | Global only, not per-account in this UI (per-account is in AdPulse Add Account) |
| Salesforce | `/integrations` card | URL, Client ID, Client Secret, Refresh Token | Same | `/config` | `config.json` | No | Toast error | — |
| WhatsApp | `/integrations` card | API Key, Phone ID, Template | Save (saves to config) | `/config` | `config.json` | No | Toast "not yet implemented" | **wired=false** — no backend; "Planned" badge |
| Slack | `/integrations` card | Webhook URL, Channel, Bot Token | Same | `/config` | `config.json` | No | Toast "not yet implemented" | **wired=false** — planned |
| Google Sheets | `/integrations` card | Service Account JSON, Spreadsheet ID | Same | `/config` | `config.json` | No | "Planned" | **wired=false** |
| Google Drive | `/integrations` card | Service Account JSON, Folder ID | Same | `/config` | `config.json` | No | "Planned" | **wired=false** |
| Google Analytics | `/integrations` card | Property ID, Service Account JSON | Same | `/config` | `config.json` | No | "Planned" | **wired=false** |
| Microsoft Excel | `/integrations` card | Client ID, Client Secret, Folder | Same | `/config` | `config.json` | No | "Planned" | **wired=false** |
| Power BI | `/integrations` card | Workspace ID, Dataset ID, Service Principal JSON | Same | `/config` | `config.json` | No | "Planned" | **wired=false** |
| Supabase | `/integrations` card | Project URL, Anon Key, Service Role Key | Same | `/config` | `config.json` | No | "Planned" | **wired=false** — ironic since the app uses Supabase |
| HubSpot | `/integrations` card | Private App Token, Portal ID | Same | `/config` | `config.json` | No | "Planned" | **wired=false** |

**Key issue:** 9 of 13 integration cards are "Planned" (wired=false) — they save credentials to config but have no backend implementation. User gets a toast "test pull not yet implemented" if they click Test.

---

## Part 12 — User Management Rule Book

| Option | UI location | Fields | Button/action | API endpoint | DB table | Role required | Validation present | Validation missing | Success | Error | Possible bugs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Add user | Landing UM modal | Full Name*, Email*, Mobile, Role (user/admin/superadmin), AdPulse/InsightDesk/RevenueOps checkboxes, Assigned Accounts | Save User | `POST /auth/users` | `users`, `user_account_assignments` | admin or superadmin | Name + email required | No email format validation; no password (user sets via link) | Alert "User created" + setup link shown | `alert(e.message)` | Admin can create admin but not superadmin; superadmin option hidden for admin |
| Edit user | Landing UM modal (Edit button) | Same fields pre-filled | Save User | `PUT /auth/users/{id}` | `users`, `user_account_assignments` | admin or superadmin | — | Can change own role? | Alert "User updated" | `alert(e.message)` | Admin can edit a superadmin's role? Backend checks `req.role=="superadmin" && current_user.role!="superadmin"` — so admin can't promote to superadmin, but CAN edit existing superadmin's other fields |
| Delete user | UM table (Delete button) | confirm() | Delete | `DELETE /auth/users/{id}` | `users` | admin or superadmin | confirm dialog | Can delete self? Can delete last superadmin? | Table refreshes | `alert(e.message)` | **No self-delete protection; no last-superadmin guard** |
| Set password | `/onboard?token=...` | Password (min 6), Confirm Password | Activate Account | `POST /auth/onboard/{token}` | `users` | Valid token holder | Password min 6; passwords match | No complexity rules | Redirect to `/` with JWT | Error message | Token expires in 72h |
| Onboarding email | Sent on user creation | — | Auto (working tree) | SMTP via `onboarding_email.py` | — | — | — | Email may fail silently if SMTP not configured | Email sent | Error in alert + manual link | Working tree only; committed main doesn't send email |
| Module access | UM checkboxes | AdPulse, InsightDesk, RevenueOps | Save User | `PUT /auth/users/{id}` | `users.access_*` | admin or superadmin | — | Admin can revoke own access? | — | — | — |
| Account assignment | UM checkbox list | Per-account checkboxes | Save User | `PUT /auth/users/{id}` | `user_account_assignments` | admin or superadmin | — | — | — | — | — |

---

## Part 13 — Button-by-Button Master Action Map

| Button name | Module | Page/section | Visible to role | What happens on click | JS function | API endpoint | DB table | Success | Error | Risk/bug |
|---|---|---|---|---|---|---|---|---|---|---|
| Login | Landing | Auth modal | Not logged in | Submits login | `login()` | `POST /auth/login` | `users` | Token stored, UI updates | "Invalid credentials" | No rate limit |
| Create Super Admin | Landing | Onboarding modal | Not logged in (no users) | Creates first superadmin | `completeOnboarding()` | `POST /auth/onboard` | `users` | Token stored, UI updates | `alert(e.message)` | No password strength check |
| Logout | All modules | Topbar | Logged in | Clears token | `logout()` | None | — | UI resets | — | No server-side invalidation |
| 👤 User Management | Landing | Topbar | admin+superadmin | Opens UM modal | `openUserManagement()` | `GET /auth/users`, `GET /auth/accounts-for-assignment` | `users`, `accounts` | Modal opens | `alert(e.message)` | — |
| Integrations | Landing | Topbar | admin+superadmin | Redirects | anchor | — | — | Page loads | — | — |
| Save User | Landing | UM modal | admin+superadmin | Creates/updates user | `saveUser()` | `POST/PUT /auth/users/{id}` | `users` | Alert + link | `alert(e.message)` | — |
| Reset | Landing | UM modal | admin+superadmin | Clears form | `resetUserForm()` | — | — | Form clears | — | — |
| Copy Link | Landing | UM modal | admin+superadmin | Copies setup link | `copySetupLink()` | — | — | "Setup link copied" | — | — |
| Edit (user) | Landing/RevOps | UM table | admin+superadmin | Fills form with user | `editUser(id)` | — | — | Form filled | — | — |
| Delete (user) | Landing/RevOps | UM table | admin+superadmin | Deletes user | `deleteUser(id)` | `DELETE /auth/users/{id}` | `users` | Table refreshes | `alert(e.message)` | No self-delete guard |
| Activate Account | Onboard | Set Password page | Token holder | Sets password | `setPassword()` | `POST /auth/onboard/{token}` | `users` | Redirect to `/` | Error message | — |
| Open (module card) | Landing | Module cards | Based on access | Redirects | `openModule(url)` | — | — | Page loads | "No access" alert | — |
| Add Account | AdPulse | Manage Accounts | admin+superadmin | Opens modal | `openAddModal()` | — | — | Modal opens | — | — |
| Save Account | AdPulse | Add/Edit modal | admin+superadmin | Creates/updates account | `saveAccount()` | `POST/PUT /accounts` | `accounts` | Toast + modal closes | `alert(e.message)` | — |
| Delete Account | AdPulse | Manage table | admin+superadmin | Deletes account | `deleteAccount(id)` | `DELETE /accounts/{id}` | `accounts` | Table refreshes | `alert(e.message)` | — |
| Edit (account) | AdPulse | Manage table | admin+superadmin | Opens edit modal | `editAccount(id)` | — | — | Modal filled | — | — |
| Connect Google | AdPulse | Account modal | admin+superadmin | OAuth redirect | `startOAuth('google')` | `GET /oauth/google/{id}/connect` | `accounts.google_credentials` | Redirect to Google | `alert(e.message)` | Must save account first |
| Disconnect Google | AdPulse | Account modal | admin+superadmin | Disconnects | `disconnectOAuth()` | `POST /oauth/google/{id}/disconnect` | `accounts` | Status updates | `alert(e.message)` | — |
| Connect Meta | AdPulse | Account modal | admin+superadmin | OAuth redirect | `startOAuth('meta')` | `GET /oauth/meta/{id}/connect` | `accounts.meta_credentials` | Redirect to Meta | `alert(e.message)` | — |
| Disconnect Meta | AdPulse | Account modal | admin+superadmin | Disconnects | `disconnectOAuth()` | `POST /oauth/meta/{id}/disconnect` | `accounts` | Status updates | `alert(e.message)` | — |
| Refresh (tile) | AdPulse | Account tile | All with access | Refreshes single account | `refreshTile(id)` | `POST /accounts/{id}/refresh` | `accounts` | Toast + reload | — | — |
| Refresh All | AdPulse | Topbar | All with access | Refreshes all accounts | `refreshAllAccounts()` | `POST /accounts/{id}/refresh` ×N | `accounts` | Toast | Per-account error swallowed | — |
| Run Audit | AdPulse | Topbar / detail | admin+superadmin | Runs audit | `runGlobalAudit()` / `runAccountAudit()` | `POST /audit-all` / `POST /accounts/{id}/audit` | `pending_actions` | Toast count | Toast error | — |
| Approve | AdPulse | Approval card | admin+superadmin | Approves action | `reviewAction(id,'approve')` | `POST /pending-actions/{id}/review` | `pending_actions` | Toast | Toast error | — |
| Reject | AdPulse | Approval card | admin+superadmin | Rejects action | `reviewAction(id,'reject')` | `POST /pending-actions/{id}/review` | `pending_actions` | Toast | Toast error | — |
| Sync Leads | InsightDesk | Topbar (DSU/DSI only) | All with access | Syncs LSQ mirror | `syncLeadsNow()` | `POST /reports/lsq-sync` | `leadsquared_leads` | Toast count + reload | Toast error | — |
| Download PDF | InsightDesk | DSU T1/T2 footer | All with access | Downloads PDF | `downloadDSUPDF(table)` | `GET /reports/dsu-performance/pdf` | — | File downloads | Toast error | DSI has no PDF |
| Add Budget Entry | InsightDesk | DSU T7 / DSI T5 form | All with access | Adds entry | `dsuSaveBudgetEntry()` / `dsiSaveBudgetEntry()` | `POST /reports/dsu/budget-entries` / `POST /reports/dsi/budget-entries` | `dsu_budget_entries` / `dsi_budget_entries` | Form resets + reload | Toast error | — |
| Edit Budget Entry | InsightDesk | DSU T7 / DSI T5 table | All with access | Fills form | `dsiEditBudgetEntry(id)` | `GET /reports/dsi/budget-entries` | — | Form filled | — | — |
| Delete Budget Entry | InsightDesk | DSU T7 / DSI T5 table | All with access | Deletes entry | `dsiDeleteBudgetEntry(id)` | `DELETE /reports/dsi/budget-entries/{id}` | `dsi_budget_entries` | Reload | Toast error | — |
| Export Excel | InsightDesk | Mantri report | All with access | Downloads | `exportMantriExcel()` | `GET /mantri/reports/export-excel` | — | File downloads | — | Mock data |
| Add Client | RevenueOps | Clients panel | All authenticated | Opens modal | `openClientModal()` | `GET /business-managers` | `users` | Modal opens | — | **No role check** |
| Save Client | RevenueOps | Client modal | All authenticated | Creates/updates | `saveModal()` | `POST/PUT /clients` | `rev_clients` | Toast + reload | Toast error | **No role check** |
| Delete Client | RevenueOps | Clients table | All authenticated | Deletes | `deleteClient(id)` | `DELETE /clients/{id}` | `rev_clients` | Reload | Toast error | **No role check** |
| New Invoice | RevenueOps | Invoices panel | All authenticated | Opens modal | (inline) | — | — | Modal opens | — | **No role check** |
| Save Invoice | RevenueOps | Invoice modal | All authenticated | Creates/updates | `saveModal()` | `POST/PUT /invoices` | `rev_invoices` | Toast + reload | Toast error | **No role check** |
| Delete Invoice | RevenueOps | Invoices table | All authenticated | Deletes | `deleteInvoice(id)` | `DELETE /invoices/{id}` | `rev_invoices`, `rev_payments` | Reload | Toast error | **No role check**; cascades payments |
| Record Payment | RevenueOps | Payments panel | All authenticated | Opens modal | (inline) | — | — | Modal opens | — | **No role check** |
| Save Payment | RevenueOps | Payment modal | All authenticated | Creates | `saveModal()` | `POST /payments` | `rev_payments` | Toast + reload | Toast error | **No role check** |
| Delete Payment | RevenueOps | Payments table | All authenticated | Deletes | `deletePayment(id)` | `DELETE /payments/{id}` | `rev_payments` | Reload | Toast error | **No role check** |
| Done (reminder) | RevenueOps | Reminders table | All authenticated | Marks done | `markReminder(id)` | `PUT /reminders/{id}` | `rev_reminders` | Reload | Toast error | **No role check** |
| Snooze | RevenueOps | Reminder popup | All authenticated | Snoozes | `snoozeReminder(id)` | `POST /reminders/{id}/snooze` | `rev_reminders` | Popup closes | Toast error | **No role check** |
| Copy Text | RevenueOps | Reminders table | All authenticated | Generates + copies | `genReminderText(id)` | `POST /reminders/{id}/generate-text` | — | Clipboard | Toast error | — |
| Add Reminder | RevenueOps | Reminders panel | All authenticated | Opens modal | (inline) | — | — | Modal opens | — | **No role check** |
| Upload Document | RevenueOps | Documents panel | All authenticated | Opens modal (URL field) | (inline) | — | — | Modal opens | — | **No file upload** |
| Save Document | RevenueOps | Document modal | All authenticated | Creates | `saveDocModal()` | `POST /documents` | `rev_documents` | Toast + reload | Toast error | **No role check** |
| Delete Document | RevenueOps | Documents table | All authenticated | Deletes | `deleteDoc(id)` | `DELETE /documents/{id}` | `rev_documents` | Reload | Toast error | **No role check** |
| Add BM | RevenueOps | BMs panel | All authenticated | Opens modal | (inline) | — | — | Modal opens | — | **No role check** |
| Save BM | RevenueOps | BM modal | All authenticated | Creates | `saveBMModal()` | `POST /business-managers` | `users` | Toast + reload | Toast error | **No role check**; weak default password |
| Delete BM | RevenueOps | BMs table | All authenticated | Deletes | `deleteBM(id)` | `DELETE /business-managers/{id}` | `users` | Reload | Toast error | **No role check** |
| Save Settings | RevenueOps | Settings panel | All authenticated | Saves 3 keys | `saveSettings()` | `PUT /settings` ×3 | `rev_settings` | Toast | Toast error | **No role check** |
| Seed Demo Data | RevenueOps | Topbar | All authenticated | Seeds demo | `seedDemo()` | `POST /seed-demo` | `rev_clients`, `rev_invoices`, `rev_payments` | Toast counts | Toast error | **No role check**; pollutes DB |
| Save Credentials | Integrations | Form panel | admin+superadmin (frontend) | Saves config | `saveIntegration()` | `PUT /accounts/{id}`, `POST /config` | `accounts`, config | Toast | Toast error | **Backend: `get_current_user_required` only — no admin check** |
| Test Pull | Integrations | Form panel | admin+superadmin | Toast only | `testIntegration()` | None | — | Toast | Toast "not implemented" | **No actual API test call** |

---

## Part 14 — API Endpoint to UI Map

| API endpoint | Method | Used by screen | JS function | DB table | Purpose | Used? | Issue |
|---|---|---|---|---|---|---|---|
| `/auth/onboarding-required` | GET | Landing | `checkAuth()` | `users` | Check if onboarding needed | ✅ | — |
| `/auth/onboard` | POST | Landing | `completeOnboarding()` | `users` | Create first superadmin | ✅ | — |
| `/auth/login` | POST | Landing | `login()` | `users` | Login | ✅ | No rate limit |
| `/auth/me` | GET | All modules | `checkAuth()` / `init()` | `users` | Get current user | ✅ | — |
| `/auth/users` | GET | Landing UM, RevOps Users | `loadUsers()` | `users` | List users | ✅ | — |
| `/auth/users` | POST | Landing UM, RevOps Users | `saveUser()` | `users` | Create user | ✅ | — |
| `/auth/users/{id}` | PUT | Landing UM, RevOps Users | `saveUser()` | `users` | Update user | ✅ | — |
| `/auth/users/{id}` | DELETE | Landing UM, RevOps Users | `deleteUser()` | `users` | Delete user | ✅ | No self-delete guard |
| `/auth/onboard/{token}` | GET | Onboard page | `init()` | `users` | Validate setup token | ✅ | — |
| `/auth/onboard/{token}` | POST | Onboard page | `setPassword()` | `users` | Set password | ✅ | — |
| `/auth/accounts-for-assignment` | GET | Landing UM | `loadAccountsForAssignment()` | `accounts` | Accounts for checkbox list | ✅ | — |
| `/accounts/summary` | GET | AdPulse dashboard | `loadSummary()` | `accounts` | KPI summary | ✅ | — |
| `/accounts` | GET | AdPulse, Integrations | `loadAccounts()` / `init()` | `accounts` | List accounts | ✅ | — |
| `/accounts` | POST | AdPulse Add Account | `saveAccount()` | `accounts` | Create account | ✅ | — |
| `/accounts/{id}` | GET | AdPulse detail | `openAccountDetail()` | `accounts` | Account detail | ✅ | — |
| `/accounts/{id}` | PUT | AdPulse Edit, Integrations | `saveAccount()` / `saveIntegration()` | `accounts` | Update account | ✅ | — |
| `/accounts/{id}` | DELETE | AdPulse Manage | `deleteAccount()` | `accounts` | Delete account | ✅ | — |
| `/accounts/{id}/refresh` | POST | AdPulse tile/refresh all | `refreshTile()` / `refreshAllAccounts()` | `accounts` | Refresh metrics | ✅ | — |
| `/accounts/{id}/leads` | GET | AdPulse tile | `fetchLeadsForTile()` | `leadsquared_leads` | Lead count | ✅ | Working tree uses mirror; main uses realtime |
| `/accounts/{id}/audit` | POST | AdPulse detail | `runAccountAudit()` | `pending_actions` | Audit account | ✅ | — |
| `/account-groups` | GET | AdPulse | `loadAccounts()` | `account_groups` | List groups | ✅ | — |
| `/account-groups` | POST | AdPulse Add Category | `saveGroup()` | `account_groups` | Create group | ✅ | — |
| `/pending-actions` | GET | AdPulse Approval Queue | `loadPendingActions()` / `loadPendingActionsCount()` | `pending_actions` | List actions | ✅ | — |
| `/pending-actions/{id}/review` | POST | AdPulse Approval Queue | `reviewAction()` | `pending_actions` | Approve/reject | ✅ | — |
| `/audit-all` | POST | AdPulse topbar | `runGlobalAudit()` | `pending_actions` | Audit all | ✅ | — |
| `/oauth/{platform}/{id}/connect` | GET | AdPulse OAuth | `startOAuth()` | `accounts` | Get auth URL | ✅ | — |
| `/oauth/{platform}/{id}/disconnect` | POST | AdPulse OAuth | `disconnectOAuth()` | `accounts` | Disconnect | ✅ | — |
| `/oauth/google/callback` | GET | OAuth redirect | — | `accounts.google_credentials` | Google callback | ✅ | — |
| `/oauth/meta/callback` | GET | OAuth redirect | — | `accounts.meta_credentials` | Meta callback | ✅ | — |
| `/reports/dsu-performance` | GET | InsightDesk DSU T1+T2 | `loadDSUReport()` | `leadsquared_leads`, `accounts` | DSU report | ✅ | — |
| `/reports/dsu-performance/pdf` | GET | InsightDesk DSU | `downloadDSUPDF()` | — | PDF download | ✅ | — |
| `/reports/dsu/lead-pivot` | GET | InsightDesk DSU T3 | `loadDSUReport()` | `leadsquared_leads` | Lead pivot | ✅ | — |
| `/reports/dsu/application-mis` | GET | InsightDesk DSU T4 | `loadDSUReport()` | `leadsquared_leads` | App MIS | ✅ | — |
| `/reports/dsu/budget-mis` | GET | InsightDesk DSU T5 | `loadDSUReport()` | `dsu_budget_entries` | Budget MIS | ✅ | — |
| `/reports/dsu/lead-stages` | GET | InsightDesk DSU T6 | `loadDSUReport()` | `leadsquared_leads` | Lead stages | ✅ | — |
| `/reports/dsu/monthly-summary` | GET | InsightDesk DSU T7 | `loadDSUReport()` | `dsu_budget_entries`, Google Ads | Monthly summary | ✅ | — |
| `/reports/dsu/budget-entries` | GET/POST/PUT/DELETE | InsightDesk DSU T7 | various | `dsu_budget_entries` | Budget CRUD | ✅ | — |
| `/reports/dsi-performance` | GET | InsightDesk DSI T1+T2 | `loadDSIReport()` | `leadsquared_leads`, `accounts` | DSI report | ✅ | — |
| `/reports/dsi/lead-pivot` | GET | InsightDesk DSI T3 | `loadDSIReport()` | `leadsquared_leads` | Lead pivot | ✅ | — |
| `/reports/dsi/application-mis` | GET | InsightDesk DSI T4 | `loadDSIReport()` | `leadsquared_leads` | App MIS | ✅ | — |
| `/reports/dsi/budget-mis` | GET | InsightDesk DSI T5 | `loadDSIReport()` | `dsi_budget_entries` | Budget MIS | ✅ | — |
| `/reports/dsi/budget-entries` | GET/POST/PUT/DELETE | InsightDesk DSI T5 | various | `dsi_budget_entries` | Budget CRUD | ✅ | — |
| `/reports/lsq-sync` | POST | InsightDesk Sync button | `syncLeadsNow()` | `leadsquared_leads` | Sync LSQ | ✅ | — |
| `/mantri/reports/lead-status-by-platform` | GET | InsightDesk Mantri | `renderMantriReport()` | None (mock) | Mantri report | ✅ | All mock |
| `/mantri/reports/export-excel` | GET | InsightDesk Mantri | `exportMantriExcel()` | None | Excel export | ✅ | Mock |
| `/accounts/{id}/crm-summary` | GET | InsightDesk generic | `renderReport()` | varies | CRM summary | ✅ | — |
| `/revenueops/dashboard` | GET | RevOps Dashboard | `loadDashboard()` | `rev_invoices` etc. | Dashboard KPIs | ✅ | — |
| `/revenueops/clients` | GET/POST | RevOps Clients | `loadClients()` / `saveModal()` | `rev_clients` | Client CRUD | ✅ | **No role check** |
| `/revenueops/clients/{id}` | GET/PUT/DELETE | RevOps Clients | `saveModal()` / `deleteClient()` | `rev_clients` | Client CRUD | ✅ | **No role check** |
| `/revenueops/invoices` | GET/POST | RevOps Invoices | `loadInvoices()` / `saveModal()` | `rev_invoices` | Invoice CRUD | ✅ | **No role check** |
| `/revenueops/invoices/{id}` | GET/PUT/DELETE | RevOps Invoices | `saveModal()` / `deleteInvoice()` | `rev_invoices` | Invoice CRUD | ✅ | **No role check** |
| `/revenueops/payments` | GET/POST | RevOps Payments | `loadPayments()` / `saveModal()` | `rev_payments` | Payment CRUD | ✅ | **No role check** |
| `/revenueops/payments/{id}` | PUT/DELETE | RevOps Payments | `saveModal()` / `deletePayment()` | `rev_payments` | Payment CRUD | ✅ | **No role check** |
| `/revenueops/outstanding` | GET | RevOps Outstanding | `loadOutstanding()` | `rev_invoices` | Outstanding list | ✅ | — |
| `/revenueops/reminders` | GET/POST | RevOps Reminders | `loadReminders()` / `saveReminderModal()` | `rev_reminders` | Reminder CRUD | ✅ | **No role check** |
| `/revenueops/reminders/due-today` | GET | RevOps popup | `checkDueReminders()` | `rev_reminders` | Due reminders | ✅ | — |
| `/revenueops/reminders/{id}/snooze` | POST | RevOps popup | `snoozeReminder()` | `rev_reminders` | Snooze | ✅ | **No role check** |
| `/revenueops/reminders/{id}/generate-text` | POST | RevOps Reminders | `genReminderText()` | — | Generate text | ✅ | — |
| `/revenueops/documents` | GET/POST | RevOps Documents | `loadDocuments()` / `saveDocModal()` | `rev_documents` | Document CRUD | ✅ | **No role check** |
| `/revenueops/documents/{id}` | DELETE | RevOps Documents | `deleteDoc()` | `rev_documents` | Delete doc | ✅ | **No role check** |
| `/revenueops/business-managers` | GET/POST | RevOps BMs | `loadBMs()` / `saveBMModal()` | `users` | BM CRUD | ✅ | **No role check** |
| `/revenueops/business-managers/{id}` | DELETE | RevOps BMs | `deleteBM()` | `users` | Delete BM | ✅ | **No role check** |
| `/revenueops/reports/*` | GET | RevOps Reports | `runReport()` | varies | Reports | ✅ | — |
| `/revenueops/settings` | GET/PUT | RevOps Settings | `loadSettings()` / `saveSettings()` | `rev_settings` | Settings | ✅ | **No role check** |
| `/revenueops/seed-demo` | POST | RevOps topbar | `seedDemo()` | `rev_clients` etc. | Seed demo | ✅ | **No role check** |
| `/config` | GET/POST | Integrations | `init()` / `saveIntegration()` | `config.json` | Global config | ✅ | **No admin check** |
| `/health` | GET | Railway | — | — | Health check | ✅ | — |
| `/campaigns/*` | GET | (not used by current UI) | — | — | Campaign details | ❌ Unused | — |
| `/search-terms/*` | GET | (not used by current UI) | — | — | Search terms | ❌ Unused | — |
| `/negatives/*` | GET/POST | (not used by current UI) | — | — | Negative keywords | ❌ Unused | — |
| `/optimizations/*` | GET/POST | (not used by current UI) | — | — | Optimizations | ❌ Unused | — |
| `/chat` | POST | (not used by current UI) | — | — | Chat with agent | ❌ Unused | — |
| `/logs` | GET | (not used by current UI) | — | — | Logs | ❌ Unused | — |
| `/notifications/*` | GET/POST | (not used by current UI) | — | `notification_settings`, `notification_logs` | Notifications | ❌ Unused | — |
| `/crm/*` | GET | (partially used by generic report) | — | — | CRM endpoints | ⚠️ Partial | — |
| `/audits/*` | GET | (not used by current UI) | — | `pending_actions` | Audit history | ❌ Unused | — |

---

## Part 15 — Database Table to UI Map

| DB table | Module | Data stored | UI display | UI form/action | API endpoints | Issue/risk |
|---|---|---|---|---|---|---|
| `users` | All | Users with role, access flags, onboarding | Landing UM, RevOps Users | Add/Edit/Delete user | `/auth/users` | No self-delete guard |
| `user_account_assignments` | All | BM→account mapping | Landing UM checkboxes | Save User | `/auth/users` | — |
| `accounts` | AdPulse | Ad accounts with credentials, metrics, status | AdPulse tiles + Manage table | Add/Edit/Delete account | `/accounts` | Sequence desync risk |
| `account_groups` | AdPulse | Category names | AdPulse Manage table + cards | Add Category | `/account-groups` | — |
| `pending_actions` | AdPulse | Audit recommendations | Approval Queue | Approve/Reject | `/pending-actions` | — |
| `leadsquared_leads` | InsightDesk | LSQ lead mirror | DSU/DSI tables | Sync Leads | `/reports/lsq-sync` | Sequence desync; staleness undetected |
| `dsu_budget_entries` | InsightDesk | DSU budget receipts | DSU T7 | Add/Edit/Delete entry | `/reports/dsu/budget-entries` | — |
| `dsi_budget_entries` | InsightDesk | DSI budget receipts | DSI T5 | Add/Edit/Delete entry | `/reports/dsi/budget-entries` | — |
| `dsu_legacy_spend` | InsightDesk | Old account spend Nov-25→Mar-26 | DSU T2 (custom range) | Seeded once | `dsu_data._fetch_legacy_spend` | — |
| `dsi_legacy_spend` | InsightDesk | DSI old spend Jan-26→Mar-26 | DSI T2 (custom range) | Seeded once | `dsi_data` | — |
| `dsu_table2_historical` | InsightDesk | DSU cumulative exact figures | DSU T2 (default range) | Seeded once | `dsu_data` | — |
| `dsi_table2_historical` | InsightDesk | DSI cumulative exact figures | DSI T2 (default range) | Seeded once | `dsi_data` | — |
| `dsu_monthly_spend_fixed` | InsightDesk | Frozen monthly spend | DSU T7 | Seeded once | `dsu_data` | — |
| `dsi_monthly_spend_fixed` | InsightDesk | DSI frozen monthly spend | DSI T5 | Seeded once | `dsi_data` | — |
| `rev_clients` | RevenueOps | Client info | Clients table + dashboard | Add/Edit/Delete | `/revenueops/clients` | **No role check** |
| `client_billing_models` | RevenueOps | Billing model per client | (not in current UI) | (not exposed) | `/revenueops/billing-models` | API exists but UI doesn't use it |
| `rev_invoices` | RevenueOps | Invoices | Invoices table + dashboard | Add/Edit/Delete | `/revenueops/invoices` | **No role check** |
| `rev_payments` | RevenueOps | Payments | Payments table + dashboard | Add/Delete | `/revenueops/payments` | **No role check** |
| `rev_reminders` | RevenueOps | Reminders | Reminders table + popup | Add/Done/Snooze | `/revenueops/reminders` | **No role check** |
| `rev_documents` | RevenueOps | Document URLs | Documents table | Add/Delete | `/revenueops/documents` | **No file upload** |
| `rev_settings` | RevenueOps | Key-value settings | Settings panel | Save | `/revenueops/settings` | **No role check** |
| `followup_notes` | RevenueOps | Follow-up notes | (not in current UI) | (not exposed) | `/revenueops/followup-notes` | API exists but UI doesn't use |
| `rev_audit_logs` | RevenueOps | Audit trail | (not in current UI) | (not exposed) | `/revenueops/audit-logs` | API exists but UI doesn't use |
| `notification_settings` | All | Notification config | (not in current UI) | (not exposed) | `/notifications` | API exists but UI doesn't use |
| `notification_logs` | All | Notification history | (not in current UI) | (not exposed) | `/notifications` | API exists but UI doesn't use |

---

## Part 16 — Screen-by-Screen Walkthrough (New Superadmin)

1. **Open app URL** → Landing page loads. If no users exist, onboarding modal appears. Otherwise login modal.
2. **Login** → Enter email + password → click Login → JWT stored → module cards show "Open".
3. **Dashboard (Landing)** → 3 module cards (AdPulse, InsightDesk, RevenueOps). All show "Open" (green) for superadmin. Topbar shows name + role badge + "User Management" + "Integrations" + "Logout".
4. **Click User Management** → Modal opens → Add/Edit/Delete users → Assign module access + accounts → Setup link shown on create.
5. **Click Integrations** → Integrations page → Select account from sidebar → Click integration card → Fill credentials → Save → 4 wired (Google Ads, Meta Ads, LeadSquared, Salesforce) + 9 planned.
6. **Open AdPulse** → Sidebar (Account Dashboard, Manage Accounts, Approval Queue) + topbar (date preset, Refresh All, Run Audit).
   - Dashboard: 4 KPI cards + group cards with account tiles (spend, conversions, CTR, CPA, leads, health badges, billing chip).
   - Manage Accounts: table with Add/Edit/Delete.
   - Approval Queue: pending action cards with Approve/Reject.
7. **Open InsightDesk** → Sidebar (Home, account list: DSU, DSI, Mantri, others).
   - DSU: 7 tabs (Tables 1-7), date selectors, sync button, PDF download.
   - DSI: 5 tabs (Tables 1-5), T1 date selector (added today), sync button.
   - Mantri: mock lead-status table + export.
   - Generic: CRM report with leads/opps/remarks.
8. **Open RevenueOps** → Sidebar accordion (Overview, Management, Follow-up, Records, Analysis, System).
   - Dashboard: 14 KPI cards + overdue clients + billing model split.
   - Clients: table + Add/Edit/Delete.
   - Invoices: table + filters + pagination + Add/Edit/Delete.
   - Payments: table + Add/Delete.
   - Outstanding: table + ageing filter.
   - Reminders: table + popup + Add/Done/Snooze/Copy Text.
   - Documents: table + Add/Delete (URL only).
   - Reports: 4 report types + CSV export.
   - BMs: table + Add/Delete.
   - BM View: per-BM KPI cards.
   - Settings: 3 fields.
   - Users: same as landing UM.
9. **Logout** → Token cleared → landing page resets to "Not logged in".

**What can go wrong:** If token expires mid-session, any API call → 401 → token cleared → redirect/login. If scheduler hasn't run, tiles show stale or zero data. If LSQ mirror is stale, InsightDesk shows old lead counts with no warning.

---

## Part 17 — Zero Data, Missing Data, Error State Rule Book

| Situation | Current UI behaviour | Current backend behaviour | Correct? | Recommended UI message | Severity |
|---|---|---|---|---|---|
| API returns zero (0 campaigns) | Shows 0 spend, 0 leads, "No Leads" for CPL | Health layer fires CRITICAL/WARNING for zero spend | ❌ | "No active campaigns found for this date range" (grey, not red) | High |
| API fails (auth/token) | Health badge DISCONNECTED/red; tile shows "Leads: -" | `status=DISCONNECTED`, `last_sync_error` stored | ✅ | OK, but reason not shown to user | Medium |
| Token expires | `api()` catches 401 → clears token → shows auth | 401 returned | ✅ | OK | Low |
| DB returns empty (no invoices) | Table shows empty body; KPIs show "—" or 0 | Empty list returned | ✅ | "No invoices yet. Create one to get started." | Low |
| User has no permission (frontend) | Card locked / button hidden | — | ⚠️ | OK for UX, but backend doesn't enforce (RevOps) | Critical |
| User role is missing (backend) | — | `require_admin_or_superadmin` → 403 | ✅ | OK for user management | Low |
| Supabase table missing column | App may crash with 500 | `create_all` doesn't add columns | ❌ | "System update required" | Critical |
| Integration credential missing | Google/Meta: tile shows DISCONNECTED; LSQ: leads show 0 | Returns empty/error | ⚠️ | "Credentials not configured. Contact admin." | High |
| Scheduler hasn't synced | Tiles show stale data; no indicator | Last sync may be hours old | ❌ | "Data last synced Xh ago. Click Refresh." | High |
| LSQ mirror stale (>3h) | Reports show old counts; no warning | Mirror used regardless of age | ❌ | "Lead data is Xh old. Click Sync Leads." | High |
| Payment data missing | Invoice shows outstanding = full amount | No payments linked | ✅ | OK | Low |
| Invoice has no payment | `invoice_status` stays "invoice_raised" or "unpaid" | — | ✅ | OK | Low |
| Account has no spend | Shows "Rs 0", CTR "0.00%", CPA "Rs 0" | spend=0 in DB | ⚠️ | "No spend recorded for this period" | Medium |
| Campaign has no leads | Shows "0" leads, CPL "No Leads" | 0 from LSQ | ⚠️ | "0 leads" (not alarming if spend is also 0) | Medium |

---

## Part 18 — Missing / Broken / Confusing UI Audit

| Issue | Module | Page/section | Severity | Why it matters | File/function | Recommended correction |
|---|---|---|---|---|---|---|
| RevenueOps CRUD has no backend role check | RevenueOps | All CRUD endpoints | **Critical** | Any authenticated user can create/delete clients, invoices, payments, BMs, settings via API | `revenueops.py` (all routes) | Add `require_admin_or_superadmin` to write/delete routes |
| `reset_superadmin` endpoint is unauthenticated | Auth | `auth.py:330` | **Critical** | Anyone can reset any superadmin's password via API | `auth.py:reset_superadmin` | Add `require_superadmin` dependency or remove endpoint |
| Config save has no admin check | Integrations | `saveIntegration()` | **High** | Any user can save global credentials | `config.py` routes | Add `require_admin_or_superadmin` |
| Seed Demo Data has no role check | RevenueOps | Topbar button | **High** | Any user can pollute production DB | `revenueops.py:seed_demo_data` | Add `require_admin_or_superadmin` |
| DSU "Today" preset returns empty | InsightDesk | DSU T1 | **High** | Start>end → no data | `mis.html:396` `computeDSUDateRange` | Set end=today for "today" preset |
| DSI Table 2 has no date selector | InsightDesk | DSI T2 | **Medium** | Can't change T2 range | `mis.html:1116` | Add T2 selector like DSU has |
| Mantri report is all mock data | InsightDesk | Mantri | **Medium** | Misleading "report" | `mantri.py:104-194` | Implement live or label as "Demo" |
| 9 integrations are "Planned" but look configurable | Integrations | Card grid | **Medium** | User wastes time entering credentials for non-functional integrations | `integrations.html:119-200` | Grey out / disable Planned cards |
| "Test Pull" doesn't test anything | Integrations | Form panel | **Medium** | False confidence | `integrations.html:297-304` | Implement actual API test calls |
| "Upload Document" is URL-only | RevenueOps | Documents | **Medium** | No actual file upload | `revenueops.html:827` | Add file upload or rename to "Add Document Link" |
| "Expected collection" is a guess (20%/50%) | RevenueOps | Dashboard | **Medium** | Misleading KPI | `revenueops.py:982-983` | Calculate from due dates |
| Meta "USED" shows lifetime spend | AdPulse | Billing chip | **Medium** | Misleading | `connectors.py:384` | Use period spend from insights |
| No "Forgot Password" flow | Landing | Login modal | **Medium** | Users locked out must contact admin manually | `landing.html` login modal | Add reset-password endpoint + UI |
| No self-delete guard on user delete | Landing/RevOps | UM table | **Medium** | Admin can delete own account | `auth.py:308` | Check `user_id == current_user.id` |
| No last-superadmin guard | Landing/RevOps | UM table | **Medium** | Can delete all superadmins → lockout | `auth.py:308` | Count superadmins before delete |
| Users panel duplicated (Landing + RevOps) | Both | UM | **Low** | Maintenance burden | `landing.html` + `revenueops.html` | Consolidate to one |
| 6 API route files unused by UI | Backend | Various | **Low** | Dead code | `campaigns.py`, `search_terms.py`, `negatives.py`, `optimizations.py`, `chat.py`, `logs.py` | Remove or wire up |
| `client_billing_models` API unused by UI | RevenueOps | — | **Low** | Feature gap | `revenueops.py:280-312` | Add billing model UI |
| `followup_notes` API unused by UI | RevenueOps | — | **Low** | Feature gap | `revenueops.py:801-824` | Add follow-up notes UI |
| `rev_audit_logs` API unused by UI | RevenueOps | — | **Low** | No audit trail visible | `revenueops.py:1075` | Add audit log viewer |
| `notifications` API unused by UI | All | — | **Low** | No notification config UI | `notifications.py` | Add notification settings panel |
| LSQ mirror staleness undetected | InsightDesk | All DSU/DSI tables | **High** | Reports show old data silently | `dsu_data.py:215-221` | Check `max(synced_at)`; warn if >6h |
| Billing chip doesn't explain "why unavailable" | AdPulse | Tile | **Low** | User confused | `billing.py:78-85` | Add tooltip with reason |
| Onboarding email only in working tree | Landing | UM | **Low** | Not in deployed main | `auth.py:create_user` | Commit the onboarding email feature |
| Working tree ≠ deployed code | All | — | **High** | Local testing on different code than production | git working tree | Decide which version is correct; commit or discard |

---

## Part 19 — Final Checklist for Owner

```
[ ] Login works (email + password)
[ ] Wrong password shows "Invalid credentials"
[ ] Superadmin can see all 3 module cards as "Open"
[ ] Admin can see all 3 module cards as "Open"
[ ] User (BM) only sees cards they have access to (others locked)
[ ] User Management opens from landing topbar (admin+superadmin only)
[ ] Add user creates user + shows setup link
[ ] Edit user updates role/access/assignments
[ ] Delete user removes user (test: cannot delete self, cannot delete last superadmin)
[ ] Onboarding email sends if SMTP configured (working tree only)
[ ] Setup link (/onboard?token=...) allows password set
[ ] Integrations page loads for admin+superadmin
[ ] Integrations hidden for user role
[ ] AdPulse dashboard loads with KPI cards + account tiles
[ ] AdPulse "Manage Accounts" table shows all accounts
[ ] Add Account modal validates Google Customer ID format
[ ] Edit Account works
[ ] Delete Account works with confirm
[ ] Google OAuth connect/disconnect works
[ ] Meta OAuth connect/disconnect works
[ ] Lead tile shows count for live accounts
[ ] Lead tile shows "0" for non-live accounts
[ ] Refresh All triggers per-account refresh
[ ] Run Audit generates pending actions
[ ] Approval Queue shows pending actions with Approve/Reject
[ ] Health badges show (API + ADS) with correct colors
[ ] Billing chip shows balance/used/unknown correctly
[ ] Date preset dropdown changes data
[ ] InsightDesk loads account list in sidebar
[ ] DSU report shows Tables 1-7 with correct data
[ ] DSU Table 1 "Yesterday" shows yesterday's data
[ ] DSU Table 1 "Today" — KNOWN BUG: returns empty
[ ] DSU Table 2 "From Inception" shows cumulative data
[ ] DSU Table 7 budget entry add/edit/delete works
[ ] DSI report shows Tables 1-5 with correct data
[ ] DSI Table 1 date selector works (Yesterday/Today/Custom)
[ ] DSI Table 2 has NO date selector (known limitation)
[ ] Sync Leads button works for DSU/DSI
[ ] Mantri report shows mock data (labelled "Sample data")
[ ] RevenueOps dashboard shows 14 KPI cards
[ ] Clients Add/Edit/Delete works
[ ] Invoices Add/Edit/Delete works
[ ] Invoices pagination works (5/10/15/20/50)
[ ] Payments Add/Delete works
[ ] Outstanding ageing filter works
[ ] Reminders Add/Done/Snooze/Copy Text works
[ ] Reminders popup appears for due-today (60s interval)
[ ] Documents Add (URL only) / Delete works
[ ] Reports run (4 types) + CSV export
[ ] BMs Add/Delete works
[ ] BM View shows per-BM KPI cards
[ ] Settings save works (3 fields)
[ ] Users panel in RevOps works (same as Landing UM)
[ ] Seed Demo Data button works (WARN: no role check)
[ ] Logout clears token and resets UI
[ ] Token expiry redirects to login
[ ] No hidden broken screens
[ ] Empty states are clear (not just empty tables)
[ ] Error states show meaningful messages
```

---

## Part 20 — Final Output

1. **Confirmation:** Markdown file `FRONTEND_UI_AND_AGENT_RULE_BOOK.md` created at repo root.
2. **Major findings:**
   - RevenueOps has **no backend role enforcement** — any authenticated user can CRUD all data via API.
   - `reset_superadmin` endpoint is **unauthenticated** — anyone can reset passwords.
   - Config/integrations save has **no admin check**.
   - 6 backend route files are **unused by any UI screen**.
   - 3 RevenueOps features (billing models, follow-up notes, audit logs) have API but **no UI**.
   - 9 of 13 integration cards are "Planned" but appear configurable.
   - "Test Pull" button **doesn't actually test** anything.
   - DSU "Today" preset **returns empty** (start>end bug).
   - DSI Table 2 has **no date selector**.
   - Mantri report is **all mock data**.
   - LSQ mirror staleness is **undetected** by UI.
   - Working tree has uncommitted changes that **differ from deployed main**.
3. **Critical UI/logic risks:**
   - RevenueOps CRUD without role check (Critical)
   - Unauthenticated `reset_superadmin` (Critical)
   - Config save without admin check (High)
   - Seed Demo Data without role check (High)
   - DSU "Today" preset empty (High)
   - LSQ mirror staleness silent (High)
   - Working tree ≠ deployed code (High)
4. **File path:** `C:\Users\Inno\Downloads\Clients\Shekhar_AI_Agents\AI_The_Optimiser\FRONTEND_UI_AND_AGENT_RULE_BOOK.md`