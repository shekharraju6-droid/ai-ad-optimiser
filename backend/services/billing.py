"""
Billing display service.

Formats billing data into a compact display chip for account cards.
Reads from cached billing_cache column (populated by scheduler).
Does NOT fetch from platform APIs directly — that happens in the scheduler.
"""
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("AdOptima")


def format_billing_amount(amount: Optional[float]) -> str:
    """Format amount as compact Indian notation: ₹850, ₹12.5K, ₹1.4L, ₹10L."""
    if amount is None:
        return "---"
    amt = float(amount)
    if amt < 0:
        amt = 0.0
    if amt < 1000:
        return f"₹{int(round(amt))}"
    if amt < 100000:
        # Show as K with one decimal (e.g. 12.5K)
        k = amt / 1000.0
        return f"₹{k:.1f}K"
    # 1,00,000+ → L format
    l = amt / 100000.0
    return f"₹{l:.1f}L"


def build_billing_display(billing_cache: Optional[str], fallback_spend: float = 0.0) -> Dict[str, Any]:
    """Build the billing display object from cached billing data.

    Returns:
        {
            billing_type: "prepaid" | "postpaid" | "unknown",
            billing_display: "BAL ₹12.9K of ₹18.8L" | "USED ₹45.2K this month" | "BILL ---",
            billing_colour: "good" | "warning" | "critical" | "neutral" | "grey",
            balance_pct: float | None (prepaid only),
            billing_amount: number | null,
        }
    """
    billing_data = None
    if billing_cache:
        try:
            billing_data = json.loads(billing_cache)
        except Exception:
            billing_data = None

    if not billing_data or billing_data.get("status") != "available":
        # No billing data — show placeholder
        if billing_data and billing_data.get("billing_type") == "postpaid":
            return {
                "billing_type": "postpaid",
                "billing_display": "USED ---",
                "billing_colour": "grey",
                "billing_amount": None,
            }
        if billing_data and billing_data.get("billing_type") == "prepaid":
            return {
                "billing_type": "prepaid",
                "billing_display": "BAL ---",
                "billing_colour": "grey",
                "billing_amount": None,
            }
        return {
            "billing_type": "unknown",
            "billing_display": "BILL ---",
            "billing_colour": "grey",
            "billing_amount": None,
        }

    # Billing data is available
    billing_type = billing_data.get("billing_type", "unknown")
    amount = billing_data.get("amount")

    if billing_type == "prepaid":
        total_budget = billing_data.get("total_budget")
        amount = billing_data.get("amount")
        balance_pct = billing_data.get("balance_pct")
        health = billing_data.get("health")

        # Compute balance_pct and health if not already cached by connector
        if balance_pct is None and amount is not None and total_budget and total_budget > 0:
            balance_pct = round((amount / total_budget * 100), 1)
        if health is None and balance_pct is not None:
            if balance_pct > 30:
                health = "good"
            elif balance_pct > 10:
                health = "warning"
            else:
                health = "critical"
        if health is None:
            health = "good"

        # Determine colour from health
        if health == "good":
            colour = "good"
        elif health == "warning":
            colour = "warning"
        elif health == "critical":
            colour = "critical"
        else:
            colour = "neutral"

        # Build display (plain text only — CSS chips handle colour/visual indicators)
        if amount is not None and total_budget:
            display = f"BAL {format_billing_amount(amount)} of {format_billing_amount(total_budget)}"
        elif amount is not None:
            display = f"BAL {format_billing_amount(amount)}"
        else:
            display = "BAL ---"
            colour = "grey"

        return {
            "billing_type": "prepaid",
            "billing_display": display,
            "billing_colour": colour,
            "balance_pct": balance_pct,
            "billing_amount": amount,
        }
    elif billing_type == "postpaid":
        monthly_spend = billing_data.get("monthly_spend", amount)
        month_label = billing_data.get("month_label", "")
        if monthly_spend is not None:
            suffix = f" this month" if not month_label else f" ({month_label})"
            display = f"USED {format_billing_amount(monthly_spend)}{suffix}"
        else:
            display = "USED ---"
        return {
            "billing_type": "postpaid",
            "billing_display": display,
            "billing_colour": "neutral",
            "billing_amount": monthly_spend,
        }
    else:
        return {
            "billing_type": "unknown",
            "billing_display": "BILL ---",
            "billing_colour": "grey",
            "billing_amount": None,
        }


def get_billing_for_account(account) -> Dict[str, Any]:
    """Get billing display for an account from its cached billing data."""
    billing_cache = getattr(account, "billing_cache", None)
    spend = float(getattr(account, "spend", 0) or 0)
    return build_billing_display(billing_cache, fallback_spend=spend)