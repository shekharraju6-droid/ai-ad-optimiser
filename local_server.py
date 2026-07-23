"""
Local Meta Leads Server
- Receives Meta Lead Ads webhooks at /webhook
- Polls Meta Insights at /poll
- Writes leads to a local SQLite database
- Forwards to Google Apps Script webhook URL (configured in .env)
"""
import os
import json
import sqlite3
import urllib.parse
import urllib.request
import threading
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, request, jsonify

load_dotenv()

app = Flask(__name__)
DB_FILE = "leads.db"
META_TOKEN = os.getenv("META_ACCESS_TOKEN")
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "act_577546498668650")
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL", "")


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY,
            source TEXT,
            created_time TEXT,
            campaign TEXT,
            adset TEXT,
            ad TEXT,
            full_name TEXT,
            email TEXT,
            phone TEXT,
            occasion TEXT,
            budget TEXT,
            purchase_timeline TEXT,
            raw_json TEXT,
            received_at TEXT
        )
    ''')
    conn.commit()
    conn.close()


def forward_to_sheet(row):
    if not APPS_SCRIPT_URL:
        return False, "No APPS_SCRIPT_URL configured"
    try:
        payload = json.dumps(row).encode("utf-8")
        req = urllib.request.Request(
            APPS_SCRIPT_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True, resp.read().decode("utf-8")
    except Exception as e:
        return False, str(e)


@app.route("/")
def home():
    return jsonify({
        "status": "running",
        "meta_token_set": bool(META_TOKEN),
        "apps_script_url_set": bool(APPS_SCRIPT_URL),
        "ad_account": AD_ACCOUNT_ID
    })


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        challenge = request.args.get("hub.challenge")
        if challenge:
            return challenge, 200
        return "OK", 200

    data = request.get_json(force=True, silent=True) or {}
    entries = data.get("entry", [])
    count = 0
    for entry in entries:
        for change in entry.get("changes", []):
            if change.get("field") != "leadgen":
                continue
            value = change.get("value", {})
            lead_id = value.get("leadgen_id")
            if not lead_id:
                continue
            lead_details = fetch_lead_details(lead_id)
            if lead_details:
                save_lead("Meta", lead_details, value.get("created_time"))
                count += 1
    return jsonify({"status": "ok", "leads_processed": count}), 200


def fetch_lead_details(lead_id):
    if not META_TOKEN:
        return None
    url = f"https://graph.facebook.com/v18.0/{lead_id}?fields=field_data,form_id,created_time,ad_id,campaign_id,adset_id&access_token={META_TOKEN}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"Error fetching lead {lead_id}: {e}")
        return None


def parse_lead_fields(lead_data):
    fields = {}
    for f in lead_data.get("field_data", []):
        fields[f.get("name", "")] = f.get("values", [""])[0] if f.get("values") else ""
    return fields


def save_lead(source, lead_data, created_time=None):
    fields = parse_lead_fields(lead_data)
    lead_id = lead_data.get("id", "unknown")
    now = datetime.now(timezone.utc).isoformat()
    created = created_time or lead_data.get("created_time") or now

    row = {
        "id": lead_id,
        "source": source,
        "created_time": created,
        "campaign": "",
        "adset": "",
        "ad": "",
        "full_name": fields.get("full_name") or fields.get("name") or "",
        "email": fields.get("email") or fields.get("email_address") or "",
        "phone": fields.get("phone_number") or fields.get("phone") or "",
        "occasion": fields.get("whats_the_occasion") or fields.get("occasion") or "",
        "budget": fields.get("whats_your_jewellery_budget") or fields.get("budget") or "",
        "purchase_timeline": fields.get("when_are_you_planning_to_purchase") or fields.get("purchase_timeline") or "",
        "raw_json": json.dumps(lead_data),
        "received_at": now
    }

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute('''
            INSERT OR REPLACE INTO leads
            (id, source, created_time, campaign, adset, ad, full_name, email, phone, occasion, budget, purchase_timeline, raw_json, received_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            row["id"], row["source"], row["created_time"], row["campaign"], row["adset"], row["ad"],
            row["full_name"], row["email"], row["phone"], row["occasion"], row["budget"],
            row["purchase_timeline"], row["raw_json"], row["received_at"]
        ))
        conn.commit()
    finally:
        conn.close()

    # Try to forward to Google Sheet via Apps Script
    if APPS_SCRIPT_URL:
        ok, msg = forward_to_sheet(row)
        print(f"Forward to sheet: {'OK' if ok else 'FAIL'} - {msg}")

    return row


@app.route("/poll")
def poll():
    if not META_TOKEN:
        return jsonify({"error": "META_ACCESS_TOKEN not configured"}), 400

    try:
        insights = fetch_insights()
        rows = build_aggregate_rows(insights)
        return jsonify({
            "status": "ok",
            "campaigns": len(insights),
            "lead_rows": len(rows),
            "data": rows[:10]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def fetch_insights():
    fields = "campaign_name,adset_name,ad_name,actions,spend,account_currency"
    params = urllib.parse.urlencode({
        "fields": fields,
        "date_preset": "today",
        "level": "ad",
        "access_token": META_TOKEN
    })
    url = f"https://graph.facebook.com/v18.0/{AD_ACCOUNT_ID}/insights?{params}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read())
        if "error" in data:
            raise Exception(data["error"])
        return data.get("data", [])


def build_aggregate_rows(insights):
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for item in insights:
        actions = item.get("actions", [])
        lead_count = 0
        for a in actions:
            if a.get("action_type") == "lead":
                lead_count = int(a.get("value", 0))
                break
        if lead_count > 0:
            rows.append({
                "timestamp": now,
                "source": "Meta",
                "campaign": item.get("campaign_name", ""),
                "adset": item.get("adset_name", ""),
                "ad": item.get("ad_name", ""),
                "event": "lead",
                "conversions": lead_count,
                "spend": item.get("spend", "0"),
                "currency": item.get("account_currency", "INR")
            })
    return rows


def background_poller():
    while True:
        try:
            if META_TOKEN:
                print(f"[{datetime.now()}] Polling Meta...")
                insights = fetch_insights()
                rows = build_aggregate_rows(insights)
                print(f"[{datetime.now()}] Found {len(rows)} lead rows")
                for row in rows:
                    print(f"  {row}")
                    if APPS_SCRIPT_URL:
                        forward_to_sheet(row)
        except Exception as e:
            print(f"[{datetime.now()}] Poll error: {e}")
        time.sleep(300)


if __name__ == "__main__":
    init_db()
    poller_thread = threading.Thread(target=background_poller, daemon=True)
    poller_thread.start()
    app.run(host="0.0.0.0", port=5000)
