"""
Meta Campaign Lead Count Poller -> Google Sheets
Pulls aggregate 'lead' conversions from Crash Club New every 5 minutes.
Requires: a valid Meta access token with ads_read permission.
"""
import os
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from dotenv import load_dotenv

# pip install gspread google-auth
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

META_TOKEN = os.getenv("META_ACCESS_TOKEN")
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "act_577546498668650")
SHEET_URL = os.getenv("GOOGLE_SHEET_URL", "https://docs.google.com/spreadsheets/d/11X4-LGdGnNXCvcRKsyUNRx8-6Sk8bhd4okHwzFcS-WU/edit")
SHEET_TAB = "Meta Leads Aggregate"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]


def get_meta_insights():
    """Fetch today's ad-level insights with lead actions."""
    fields = "campaign_name,adset_name,ad_name,actions,spend,account_currency"
    params = {
        "fields": fields,
        "date_preset": "today",
        "level": "ad",
        "access_token": META_TOKEN,
    }
    url = f"https://graph.facebook.com/v18.0/{AD_ACCOUNT_ID}/insights?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
        return data.get("data", [])


def build_rows(insights):
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for item in insights:
        actions = item.get("actions", [])
        lead_count = 0
        for action in actions:
            if action.get("action_type") == "lead":
                lead_count = int(action.get("value", 0))
                break
        if lead_count > 0:
            rows.append([
                now,
                "Meta",
                item.get("campaign_name", ""),
                item.get("adset_name", ""),
                item.get("ad_name", ""),
                "lead",
                lead_count,
                item.get("spend", "0"),
                item.get("account_currency", "INR"),
            ])
    return rows


def append_to_sheet(rows):
    creds = Credentials.from_service_account_file("google_service_account.json", scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url(SHEET_URL)
    try:
        worksheet = spreadsheet.worksheet(SHEET_TAB)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=SHEET_TAB, rows=1000, cols=9)
        worksheet.append_row([
            "Timestamp", "Source", "Campaign", "Ad Set", "Ad",
            "Conversion Event", "Conversions", "Spend (INR)", "Currency"
        ])
    for row in rows:
        worksheet.append_row(row)


def run_once():
    if not META_TOKEN or META_TOKEN == "YOUR_TOKEN_HERE":
        print("ERROR: META_ACCESS_TOKEN not set in .env")
        return
    insights = get_meta_insights()
    rows = build_rows(insights)
    if rows:
        append_to_sheet(rows)
        print(f"Wrote {len(rows)} rows to Google Sheet")
    else:
        print("No lead conversions found")


def run_loop():
    print("Poller started. Runs every 5 minutes. Press Ctrl+C to stop.")
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(300)


if __name__ == "__main__":
    run_once()
