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

    Args:
        billing_cache: JSON string from account.billing_cache (populated by scheduler).
        fallback_spend: Today's spend, used as postpaid 'USED' fallback if billing
                        data is unavailable but we have spend.

    Returns:
        {
            billing_type: "prepaid" | "postpaid" | "unknown",
            billing_label: "BAL" | "USED" | "BILL",
            billing_amount: number | null,
            billing_display: "BAL ₹12.5K" | "USED ₹4.2K" | "BILL ---",
            billing_status: "available" | "unavailable",
            color: "neutral" | "yellow" | "red" | "grey",
        }
    """
    billing_data = None
    if billing_cache:
        try:
            billing_data = json.loads(billing_cache)
        except Exception:
            billing_data = None

    if not billing_data or billing_data.get("status") != "available":
        # No billing data — show placeholder, do NOT fall back to spend as USED
        if billing_data and billing_data.get("billing_type") == "postpaid":
            return {
                "billing_type": "postpaid",
                "billing_label": "USED",
                "billing_amount": None,
                "billing_display": "USED ---",
                "billing_status": "unavailable",
                "color": "grey",
            }
        if billing_data and billing_data.get("billing_type") == "prepaid":
            return {
                "billing_type": "prepaid",
                "billing_label": "BAL",
                "billing_amount": None,
                "billing_display": "BAL ---",
                "billing_status": "unavailable",
                "color": "grey",
            }
        return {
            "billing_type": "unknown",
            "billing_label": "BILL",
            "billing_amount": None,
            "billing_display": "BILL ---",
            "billing_status": "unavailable",
            "color": "grey",
        }

    # Billing data is available
    billing_type = billing_data.get("billing_type", "unknown")
    amount = billing_data.get("amount")
    total_budget = billing_data.get("total_budget")

    if billing_type == "prepaid":
        label = "BAL"
        color = "neutral"
        if amount is not None:
            if amount <= 0:
                color = "red"
            elif total_budget and total_budget > 0 and amount < (total_budget * 0.10):
                # Low balance: below 10% of total budget
                color = "yellow"
            elif amount < 500:  # Low absolute balance threshold
                color = "yellow"
        else:
            color = "grey"

        # Display: BAL ₹xx / ₹yy if total_budget available
        if amount is not None and total_budget:
            display = f"BAL {format_billing_amount(amount)} / {format_billing_amount(total_budget)}"
        elif amount is not None:
            display = f"BAL {format_billing_amount(amount)}"
        else:
            display = "BAL ---"
    elif billing_type == "postpaid":
        label = "USED"
        color = "neutral"
        if amount is not None:
            display = f"USED {format_billing_amount(amount)}"
        else:
            display = "USED ---"
    else:
        label = "BILL"
        color = "grey"
        display = "BILL ---"

    return {
        "billing_type": billing_type,
        "billing_label": label,
        "billing_amount": amount,
        "billing_display": display,
        "billing_status": "available" if amount is not None else "unavailable",
        "color": color,
    }


def get_billing_for_account(account) -> Dict[str, Any]:
    """Get billing display for an account from its cached billing data."""
    billing_cache = getattr(account, "billing_cache", None)
    spend = float(getattr(account, "spend", 0) or 0)
    return build_billing_display(billing_cache, fallback_spend=spend)