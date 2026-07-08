"""Diagnostic: dump raw account_budget fields for DSU and DSI."""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.db.database import SessionLocal
from backend.db.models import Account
from backend.services.connectors import GoogleAdsConnector


def _today_ist():
    from datetime import datetime, timezone, timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime("%Y-%m-%d")


def diag_account(account_name: str):
    db = SessionLocal()
    try:
        account = db.query(Account).filter(Account.name == account_name).first()
        if not account:
            print(f"\n=== {account_name}: NOT FOUND ===")
            return

        print(f"\n=== {account_name} (id={account.id}) ===")
        print(f"  google_external_id       : {account.google_external_id}")
        print(f"  google_login_customer_id : {account.google_login_customer_id}")
        print(f"  billing_cache            : {account.billing_cache}")

        conn = GoogleAdsConnector(account)
        if not conn.is_valid:
            print("  GoogleAdsConnector: NOT VALID")
            return

        service = conn.client.get_service("GoogleAdsService")
        customer_id = (account.google_external_id or account.external_id or "").replace("-", "")
        print(f"  customer_id              : {customer_id}")

        # Diagnostic query: all fields for all account_budget records
        query_diag = """
            SELECT
              account_budget.id,
              account_budget.name,
              account_budget.status,
              account_budget.approved_spending_limit_micros,
              account_budget.adjusted_spending_limit_micros,
              account_budget.amount_served_micros,
              account_budget.approved_start_date_time,
              account_budget.approved_end_date_time
            FROM account_budget
        """
        print("\n  --- account_budget records ---")
        try:
            response = service.search(customer_id=customer_id, query=query_diag)
            count = 0
            for row in response:
                count += 1
                ab = row.account_budget
                print(f"\n  Record #{count}:")
                print(f"    id                              : {ab.id}")
                print(f"    name                            : {ab.name}")
                print(f"    status                          : {ab.status}")
                print(f"    approved_spending_limit_micros  : {ab.approved_spending_limit_micros}")
                print(f"    adjusted_spending_limit_micros  : {ab.adjusted_spending_limit_micros}")
                print(f"    amount_served_micros            : {ab.amount_served_micros}")
                print(f"    approved_start_date_time        : {ab.approved_start_date_time}")
                print(f"    approved_end_date_time          : {ab.approved_end_date_time}")
                # Derived
                adj_limit = ab.adjusted_spending_limit_micros or 0
                served = ab.amount_served_micros or 0
                balance_served = (adj_limit - served) / 1_000_000.0
                print(f"    -> balance (adj_limit - served) : {balance_served:.2f}")
            if count == 0:
                print("    (no account_budget records returned)")
        except Exception as e:
            print(f"  ERROR on diagnostic query: {e}")

        # Also fetch customer-level monthly spend for comparison
        today_ist = _today_ist()
        first_of_month = today_ist[:8] + "01"
        query_month = f"""
            SELECT
              customer.id,
              metrics.cost_micros
            FROM customer
            WHERE segments.date BETWEEN '{first_of_month}' AND '{today_ist}'
        """
        print(f"\n  --- customer THIS_MONTH spend ({first_of_month} to {today_ist}) ---")
        try:
            response_month = service.search(customer_id=customer_id, query=query_month)
            total_month = 0.0
            for row in response_month:
                total_month += (row.metrics.cost_micros or 0) / 1_000_000.0
            print(f"    monthly spend : {total_month:.2f}")
        except Exception as e:
            print(f"  ERROR on monthly query: {e}")

        # Also fetch spend since budget start date (what we currently use)
        try:
            cache = json.loads(account.billing_cache) if account.billing_cache else {}
            budget_start = cache.get("budget_start_date", "2026-04-02")
        except Exception:
            budget_start = "2026-04-02"
        query_spend = f"""
            SELECT
              metrics.cost_micros
            FROM customer
            WHERE segments.date BETWEEN '{budget_start}' AND '{today_ist}'
        """
        print(f"\n  --- customer spend since budget_start ({budget_start} to {today_ist}) ---")
        try:
            response_spend = service.search(customer_id=customer_id, query=query_spend)
            total_spend = 0.0
            for row in response_spend:
                total_spend += (row.metrics.cost_micros or 0) / 1_000_000.0
            print(f"    spend_since_budget_start : {total_spend:.2f}")
            print(f"    (this is what we subtract from total_budget currently)")
        except Exception as e:
            print(f"  ERROR on spend query: {e}")

    finally:
        db.close()


if __name__ == "__main__":
    for name in ["DSU", "DSI"]:
        try:
            diag_account(name)
        except Exception as e:
            print(f"\n=== {name}: FAILED with exception ===")
            import traceback
            traceback.print_exc()