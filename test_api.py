"""
AdOptima AI - Expanded Integration Tests
Tests the core API endpoints for the restructured backend.
"""
import requests
import json

BASE_URL = "http://127.0.0.1:8000"


def test_status_and_config():
    print("[*] Testing /api/config...")
    res = requests.get(f"{BASE_URL}/api/config")
    assert res.status_code == 200
    data = res.json()
    assert "mock_mode" in data
    print(f"[+] Config loaded. Mock Mode: {data.get('mock_mode')}, Safe Mode: {data.get('safe_mode')}")


def test_campaigns():
    print("[*] Testing /api/campaigns...")
    res = requests.get(f"{BASE_URL}/api/campaigns")
    assert res.status_code == 200
    campaigns = res.json()
    print(f"[+] Loaded {len(campaigns)} campaigns.")
    assert any(c["id"] == "104" for c in campaigns)
    bba = next(c for c in campaigns if c["id"] == "104")
    assert bba["name"] == "BBA - Brand"
    print("[+] Verified BBA - Brand campaign is present.")


def test_search_terms():
    print("[*] Testing /api/search-terms...")
    res = requests.get(f"{BASE_URL}/api/search-terms?campaign_id=104")
    assert res.status_code == 200
    terms = res.json()
    print(f"[+] Loaded {len(terms)} search terms for BBA campaign.")
    assert any("kristhu jayanthi" in t["term"].lower() for t in terms)
    assert any("college predictor" in t["term"].lower() for t in terms)
    print("[+] Verified competitor and low-intent terms are present.")


def test_negative_keywords_flow():
    print("[*] Testing BBA negative keyword flow...")
    initial = requests.get(f"{BASE_URL}/api/search-terms?campaign_id=104").json()
    initial_count = len(initial)

    res = requests.post(
        f"{BASE_URL}/api/negative-keywords",
        json={"campaign_id": "104", "keyword": "kristhu jayanthi", "match_type": "PHRASE"},
    )
    assert res.status_code == 200
    print("[+] Added phrase negative 'kristhu jayanthi'.")

    res = requests.post(
        f"{BASE_URL}/api/negative-keywords",
        json={"campaign_id": "104", "keyword": "college predictor", "match_type": "EXACT"},
    )
    assert res.status_code == 200
    print("[+] Added exact negative 'college predictor'.")

    after = requests.get(f"{BASE_URL}/api/search-terms?campaign_id=104").json()
    assert not any("kristhu jayanthi" in t["term"].lower() for t in after)
    assert not any("college predictor" in t["term"].lower() for t in after)
    print(f"[+] Filter verified: {initial_count} -> {len(after)} terms.")

    requests.post(f"{BASE_URL}/api/reset-mock")
    print("[+] Mock DB reset.")


def test_audit():
    print("[*] Testing /api/audit...")
    res = requests.get(f"{BASE_URL}/api/audit?campaign_id=104")
    assert res.status_code == 200
    audit = res.json()
    assert audit["campaigns_audited"] == 1
    assert audit["estimated_waste"] > 0
    assert any(r["type"] == "ADD_NEGATIVE_KEYWORD" for r in audit["recommendations"])
    print(f"[+] Audit returned {audit['problematic_terms']} problematic terms, ${audit['estimated_waste']:.2f} waste.")


def test_reports():
    print("[*] Testing /api/report/full...")
    res = requests.get(f"{BASE_URL}/api/report/full")
    assert res.status_code == 200
    report = res.json()
    assert "audit" in report
    assert "savings" in report
    assert "waste_breakdown" in report
    print(f"[+] Report loaded. Negatives added: {report['savings']['negative_keywords_added']}")


def test_chat_agent():
    print("[*] Testing chat agent BBA audit...")
    payload = {"message": "Audit my search terms in BBA brand campaign to find waste", "history": []}
    res = requests.post(f"{BASE_URL}/api/chat", json=payload)
    assert res.status_code == 200
    data = res.json()
    response_text = data.get("response", "")
    assert "BBA - Brand" in response_text or "BBA" in response_text
    assert any(k in response_text.lower() for k in ["kristhu", "competitor", "waste"])
    print("[+] Chat agent correctly identified BBA campaign issues.")


def test_auth():
    print("[*] Testing /api/auth/login...")
    res = requests.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert res.status_code == 200
    data = res.json()
    assert "token" in data
    print(f"[+] Login successful. Accounts: {data['accounts']}")

    me = requests.get(f"{BASE_URL}/api/auth/me", headers={"x-auth-token": data["token"]})
    assert me.status_code == 200
    print("[+] Auth session verified.")


if __name__ == "__main__":
    print("--- Running AdOptima AI Integration Tests ---")
    test_status_and_config()
    test_campaigns()
    test_search_terms()
    test_negative_keywords_flow()
    test_audit()
    test_reports()
    test_chat_agent()
    test_auth()
    print("--- All tests PASSED successfully! ---")
