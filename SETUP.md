# Meta Leads Aggregate -> Google Sheets Setup

## What this does
Every 5 minutes, pulls aggregate "lead" conversion counts from Meta ad account `Crash Club New` and writes to a Google Sheet tab called **"Meta Leads Aggregate"**.

## What you still need
1. A valid Meta access token with `ads_read` permission.
2. A Google service account JSON file with access to the Google Sheet.

## Files
- `meta_leads_poller.py` — local Python poller
- `google_apps_script_poller.js` — Google Apps Script poller (alternative, runs in Google's servers)
- `setup.bat` — creates Windows Task Scheduler entry for local poller
- `.env` — configuration file

## Steps

### 1. Meta Token
The token must be valid and have `ads_read` permission. Replace in `.env`:
```
META_ACCESS_TOKEN=YOUR_VALID_TOKEN
```

### 2. Google Service Account
1. Go to https://console.cloud.google.com/
2. Create a service account.
3. Enable Google Sheets API and Google Drive API.
4. Download the JSON key and save as `google_service_account.json` in this folder.
5. Share the Google Sheet with the service account email (e.g., `your-service@project.iam.gserviceaccount.com`).

### 3. Install dependencies
Open PowerShell in this folder and run:
```powershell
pip install gspread google-auth python-dotenv
```

### 4. Run once manually
```powershell
python meta_leads_poller.py
```

### 5. Schedule every 5 minutes
Run `setup.bat` as Administrator, or manually create a scheduled task that runs:
```
python meta_leads_poller.py
```
every 5 minutes.

## Alternative: Google Apps Script
If you prefer no local setup:
1. In the Sheet, click Extensions → Apps Script.
2. Replace default code with contents of `google_apps_script_poller.js`.
3. Run `saveToken()` once (paste valid Meta token).
4. Run `createSheet()` once.
5. Run `setupTrigger()` once.
6. Authorize all permissions.

## Limitation
This pulls aggregate lead counts only, not individual lead names/phone/emails. For individual leads, Meta requires `pages_manage_ads` + `leads_retrieval` permissions via App Review.
