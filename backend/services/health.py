"""
Health badge evaluation layer.

Computes two badges per ad account:
  1. API Connection Health  — did the platform API call succeed and is sync fresh?
  2. Performance Health     — is the campaign actually delivering and performing?

This module is platform-agnostic. It receives normalized metrics (spend, clicks,
impressions, conversions, leads, ctr, cpa, target_cpa, campaign_status, etc.)
and returns badge dicts. It never fetches data itself — callers feed it the
metrics they already have.

Badge dict shape:
  {
    "status": "GOOD" | "WARNING" | "CRITICAL" | "DISCONNECTED" | "UNKNOWN",
    "color":  "green" | "yellow" | "red" | "grey",
    "reason": str,
    "triggered_metric": str,
    "recommended_action": str,
  }
"""
from __future__ import annotations

from datetime import datetime, timedelta, date
from typing import Any, Dict, Optional


# Default active ad schedule (local account time)
DEFAULT_ACTIVE_START = 9   # 9:00 AM
DEFAULT_ACTIVE_END = 21     # 9:00 PM (21:00)
ACTIVE_HOURS_TOTAL = DEFAULT_ACTIVE_END - DEFAULT_ACTIVE_START  # 12 hours

# Stale sync threshold (hours)
STALE_SYNC_HOURS = 3

# --- Configurable thresholds (not hardcoded permanently) ---
# 24-hour schedule: active_start=0, active_end=23 (treated as 23:59)
# Default schedule is 9-21 (12 hours)

# Minimum meaningful spend (₹) when no daily budget is available.
# Spend below this after 30% of day → WARNING; after 50% → CRITICAL.
MIN_MEANINGFUL_SPEND_WARNING = 50.0    # ₹50
MIN_MEANINGFUL_SPEND_CRITICAL = 100.0  # ₹100

# Spend pacing ratios (actual_spend / expected_spend_so_far)
PACING_WARNING_RATIO = 0.25   # <25% of expected → WARNING
PACING_CRITICAL_RATIO = 0.20  # <20% of expected → CRITICAL

# Micro-spend threshold: spend > 0 but below this is "micro-spend"
MICRO_SPEND_THRESHOLD = 50.0  # ₹50


def _now_ist() -> datetime:
    """Current time in IST (UTC+5:30). All AdOptima accounts use Asia/Kolkata."""
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def _active_day_progress(
    now: datetime,
    active_start: int = DEFAULT_ACTIVE_START,
    active_end: int = DEFAULT_ACTIVE_END,
) -> float:
    """Fraction of the active ad-schedule day that has elapsed (0.0 to 1.0).

    For 24-hour campaigns: active_start=0, active_end=23.
    Progress = elapsed minutes today / total minutes in active window.
    """
    if active_end <= active_start:
        return 1.0

    total_minutes = (active_end - active_start) * 60 + 59  # e.g. 23:59 → 23*60+59
    elapsed_minutes = (now.hour - active_start) * 60 + now.minute
    if now.hour < active_start:
        return 0.0
    if now.hour >= active_end:
        return 1.0
    return min(elapsed_minutes / total_minutes, 1.0)


# ---------------------------------------------------------------------------
# Badge 1: API Connection Health
# ---------------------------------------------------------------------------

def compute_api_health(
    *,
    api_success: bool,
    last_sync_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
    platform: str = "google",
) -> Dict[str, Any]:
    """Evaluate API connection health.

    Args:
        api_success: True if the most recent platform API call returned data
                     without authentication / permission / network errors.
        last_sync_at: UTC datetime of the last successful sync (may be None).
        now: Current datetime in the account timezone (defaults to IST now).
        platform: "google" or "meta" — used for the reason string.
    """
    if now is None:
        now = _now_ist()

    plat_label = "Google Ads" if platform == "google" else "Meta Ads"

    if not api_success:
        return {
            "status": "DISCONNECTED",
            "color": "red",
            "reason": f"{plat_label} API call failed — authentication, token, or permission issue.",
            "triggered_metric": "api_call = failed",
            "recommended_action": f"Check {plat_label} OAuth credentials, refresh token, and API permissions.",
        }

    # API succeeded — check sync freshness
    if last_sync_at is None:
        return {
            "status": "WARNING",
            "color": "yellow",
            "reason": f"{plat_label} API responded but last sync time is missing.",
            "triggered_metric": "last_sync_at = null",
            "recommended_action": "Run a manual refresh to populate sync status.",
        }

    # last_sync_at is stored in UTC; convert to IST for comparison
    sync_ist = last_sync_at + timedelta(hours=5, minutes=30)
    hours_since = (now - sync_ist).total_seconds() / 3600.0
    if hours_since > STALE_SYNC_HOURS:
        return {
            "status": "WARNING",
            "color": "yellow",
            "reason": f"{plat_label} API succeeded but last sync was {hours_since:.0f} hours ago.",
            "triggered_metric": f"hours_since_sync = {hours_since:.0f}",
            "recommended_action": "Refresh account metrics to bring sync up to date.",
        }

    return {
        "status": "GOOD",
        "color": "green",
        "reason": f"{plat_label} API is connected and data synced successfully.",
        "triggered_metric": "api_call = success, sync fresh",
        "recommended_action": "No action needed.",
    }


# ---------------------------------------------------------------------------
# Badge 2: Performance Health
# ---------------------------------------------------------------------------

def compute_perf_health(
    *,
    api_success: bool,
    campaign_active: bool = True,
    spend: float = 0.0,
    impressions: int = 0,
    clicks: int = 0,
    conversions: float = 0.0,
    leads: int = 0,
    ctr: float = 0.0,
    cpc: float = 0.0,
    cpa: float = 0.0,
    target_cpa: Optional[float] = None,
    daily_budget: Optional[float] = None,
    active_start: int = DEFAULT_ACTIVE_START,
    active_end: int = DEFAULT_ACTIVE_END,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Evaluate performance health using available metrics.

    Only uses metrics that are provided; missing metrics are skipped.
    Never crashes on missing data.

    Args:
        daily_budget: Daily budget for pacing calculation. If None, fallback
                      thresholds (MIN_MEANINGFUL_SPEND_*) are used.
        active_start: Hour when the active ad schedule starts (0-23).
        active_end:   Hour when the active ad schedule ends (0-23, treated as HH:59).
    """
    if now is None:
        now = _now_ist()

    # Rule 1: API failed → UNKNOWN
    if not api_success:
        return {
            "status": "UNKNOWN",
            "color": "grey",
            "reason": "Performance cannot be evaluated because API data is unavailable.",
            "triggered_metric": "api_call = failed",
            "recommended_action": "Restore API connection first.",
        }

    # Rule 2: Campaign blocked / paused
    if not campaign_active:
        return {
            "status": "CRITICAL",
            "color": "red",
            "reason": "Campaign/account is paused, suspended, removed, or disabled.",
            "triggered_metric": "campaign_active = false",
            "recommended_action": "Check campaign status, billing, and policy compliance.",
        }

    progress = _active_day_progress(now, active_start, active_end)
    pct = int(progress * 100)

    # --- Spend pacing ---
    # If daily_budget available, compute expected spend and pacing ratio.
    # Otherwise use fallback minimum meaningful spend thresholds.
    if daily_budget and daily_budget > 0:
        expected_spend = daily_budget * progress
        pacing_ratio = (spend / expected_spend) if expected_spend > 0 else 0.0
        pacing_str = f"spend = ₹{spend:.0f}, expected = ₹{expected_spend:.0f}, pacing = {pacing_ratio*100:.0f}%"
    else:
        expected_spend = 0.0
        pacing_ratio = 1.0  # neutral; use fallback thresholds instead
        pacing_str = f"spend = ₹{spend:.0f}, daily_budget = n/a"

    # Determine if spend is "zero", "micro", or "meaningful"
    if spend < 1.0:
        spend_category = "zero"
    elif spend < MICRO_SPEND_THRESHOLD:
        spend_category = "micro"
    else:
        spend_category = "meaningful"

    # --- Priority-ordered checks ---

    # CRITICAL: spend is 0 after 50% of active day
    if spend_category == "zero" and progress >= 0.50:
        return {
            "status": "CRITICAL",
            "color": "red",
            "reason": f"Campaign is active but spend is 0 after {pct}% of the active day has passed.",
            "triggered_metric": f"spend = 0, active_day_progress = {pct}%",
            "recommended_action": "Check budget, bid strategy, campaign eligibility, ad approval, targeting size, and recent campaign changes.",
        }

    # CRITICAL: impressions are 0 after 50% of active day
    if impressions <= 0 and progress >= 0.50:
        return {
            "status": "CRITICAL",
            "color": "red",
            "reason": f"Campaign is active but impressions are 0 after {pct}% of the active day has passed.",
            "triggered_metric": f"impressions = 0, active_day_progress = {pct}%",
            "recommended_action": "Check ad approvals, targeting, and campaign delivery settings.",
        }

    # CRITICAL: spend pacing severely under (50% of day, <20% of expected)
    if daily_budget and daily_budget > 0 and progress >= 0.50 and pacing_ratio < PACING_CRITICAL_RATIO:
        return {
            "status": "CRITICAL",
            "color": "red",
            "reason": f"Campaign is active but spend is only {pacing_ratio*100:.0f}% of expected after {pct}% of the active day.",
            "triggered_metric": pacing_str + f", active_day_progress = {pct}%",
            "recommended_action": "Check budget, bid strategy, campaign eligibility, ad approval, targeting size, and recent campaign changes.",
        }

    # CRITICAL: micro/zero spend after 50% (fallback when no daily budget)
    if spend_category != "meaningful" and progress >= 0.50 and (not daily_budget or daily_budget <= 0):
        if spend < MIN_MEANINGFUL_SPEND_CRITICAL:
            return {
                "status": "CRITICAL",
                "color": "red",
                "reason": f"Campaign is active but spend is only ₹{spend:.0f} after {pct}% of the active day has passed.",
                "triggered_metric": f"spend = ₹{spend:.0f}, active_day_progress = {pct}%",
                "recommended_action": "Check budget, bid strategy, campaign eligibility, ad approval, targeting size, and recent campaign changes.",
            }

    # WARNING: spend is 0 after 30% of active day
    if spend_category == "zero" and progress >= 0.30:
        return {
            "status": "WARNING",
            "color": "yellow",
            "reason": f"Campaign is active but spend is 0 after {pct}% of the active day has passed.",
            "triggered_metric": f"spend = 0, active_day_progress = {pct}%",
            "recommended_action": "Check campaign delivery, budget, bid strategy, ad approval, and conversion tracking.",
        }

    # WARNING: impressions are 0 after 30% of active day
    if impressions <= 0 and progress >= 0.30:
        return {
            "status": "WARNING",
            "color": "yellow",
            "reason": f"Campaign is active but impressions are 0 after {pct}% of the active day has passed.",
            "triggered_metric": f"impressions = 0, active_day_progress = {pct}%",
            "recommended_action": "Check ad approvals, targeting, and campaign delivery settings.",
        }

    # WARNING: spend pacing under (30% of day, <25% of expected)
    if daily_budget and daily_budget > 0 and progress >= 0.30 and pacing_ratio < PACING_WARNING_RATIO:
        return {
            "status": "WARNING",
            "color": "yellow",
            "reason": f"Campaign is active but spend is only {pacing_ratio*100:.0f}% of expected after {pct}% of the active day.",
            "triggered_metric": pacing_str + f", active_day_progress = {pct}%",
            "recommended_action": "Check budget, bid strategy, campaign eligibility, ad approval, targeting size, and recent campaign changes.",
        }

    # WARNING: micro-spend after 30% (no daily budget fallback)
    if spend_category == "micro" and progress >= 0.30 and (not daily_budget or daily_budget <= 0):
        return {
            "status": "WARNING",
            "color": "yellow",
            "reason": f"Campaign is active, but spend is extremely low (₹{spend:.0f}) after {pct}% of the active day has passed.",
            "triggered_metric": f"spend = ₹{spend:.0f}, active_day_progress = {pct}%",
            "recommended_action": "Check budget, bid strategy, campaign eligibility, ad approval, targeting size, and recent campaign changes.",
        }

    # WARNING: micro-spend after 30% (daily budget available but pacing check passed — still micro)
    if spend_category == "micro" and progress >= 0.30:
        return {
            "status": "WARNING",
            "color": "yellow",
            "reason": f"Campaign is active, but spend is extremely low (₹{spend:.0f}) after {pct}% of the active day has passed.",
            "triggered_metric": f"spend = ₹{spend:.0f}, active_day_progress = {pct}%",
            "recommended_action": "Check budget, bid strategy, campaign eligibility, ad approval, targeting size, and recent campaign changes.",
        }

    # WARNING: meaningful impressions but 0 clicks
    if impressions >= 500 and clicks <= 0:
        return {
            "status": "WARNING",
            "color": "yellow",
            "reason": f"Impressions are meaningful ({impressions}) but clicks are 0.",
            "triggered_metric": f"impressions = {impressions}, clicks = 0",
            "recommended_action": "Review ad creative, relevance, and landing page alignment.",
        }

    # effective leads = CRM leads or platform conversions
    effective_leads = leads if leads > 0 else int(conversions) if conversions > 0 else 0

    # WARNING: clicks >= 20 but 0 leads/conversions
    if clicks >= 20 and effective_leads <= 0:
        if target_cpa and target_cpa > 0 and spend >= 1.5 * target_cpa:
            return {
                "status": "CRITICAL",
                "color": "red",
                "reason": f"Spend (₹{spend:.0f}) crossed 1.5x target CPA (₹{target_cpa:.0f}) with 0 leads/conversions.",
                "triggered_metric": f"spend = {spend}, target_cpa = {target_cpa}, leads = 0",
                "recommended_action": "Pause underperforming campaigns, review conversion tracking, and adjust targeting.",
            }
        return {
            "status": "WARNING",
            "color": "yellow",
            "reason": f"Clicks are meaningful ({clicks}) but leads/conversions are 0.",
            "triggered_metric": f"clicks = {clicks}, leads = {effective_leads}",
            "recommended_action": "Check conversion tracking, landing page, and lead capture flow.",
        }

    # WARNING: spend approaching target CPA with 0 leads
    if target_cpa and target_cpa > 0 and spend >= 0.7 * target_cpa and effective_leads <= 0:
        return {
            "status": "WARNING",
            "color": "yellow",
            "reason": f"Spend (₹{spend:.0f}) approaching target CPA (₹{target_cpa:.0f}) with 0 leads/conversions.",
            "triggered_metric": f"spend = {spend}, target_cpa = {target_cpa}, leads = 0",
            "recommended_action": "Monitor closely; review conversion tracking and campaign targeting.",
        }

    # WARNING/CRITICAL: CPA vs target
    if target_cpa and target_cpa > 0 and effective_leads > 0 and cpa > 0:
        if cpa >= 1.5 * target_cpa:
            return {
                "status": "CRITICAL",
                "color": "red",
                "reason": f"CPA (₹{cpa:.0f}) is {cpa/target_cpa*100:.0f}% of target (₹{target_cpa:.0f}).",
                "triggered_metric": f"cpa = {cpa}, target_cpa = {target_cpa}",
                "recommended_action": "Reduce bids, refine targeting, pause high-CPA campaigns.",
            }
        if cpa >= 1.2 * target_cpa:
            return {
                "status": "WARNING",
                "color": "yellow",
                "reason": f"CPA (₹{cpa:.0f}) is {cpa/target_cpa*100:.0f}% of target (₹{target_cpa:.0f}).",
                "triggered_metric": f"cpa = {cpa}, target_cpa = {target_cpa}",
                "recommended_action": "Optimise bids and targeting to bring CPA within target.",
            }

    # All checks passed → GOOD
    return {
        "status": "GOOD",
        "color": "green",
        "reason": "Campaign is active with delivery and performance within expected range.",
        "triggered_metric": "spend > threshold, impressions > 0, no critical issues",
        "recommended_action": "No action needed.",
    }


# ---------------------------------------------------------------------------
# Combined helper
# ---------------------------------------------------------------------------

def compute_health_badges(
    account,
    *,
    api_success: bool,
    platform: str = "google",
    leads: int = 0,
    daily_budget: Optional[float] = None,
    active_start: int = DEFAULT_ACTIVE_START,
    active_end: int = DEFAULT_ACTIVE_END,
    now: Optional[datetime] = None,
) -> Dict[str, Dict[str, Any]]:
    """Compute both API and Performance health badges for an account.

    Args:
        account: The Account ORM object (provides spend, clicks, impressions,
                 conversions, ctr, cpa, target_cpa, last_sync_at, is_live, etc.).
        api_success: Whether the most recent platform API call succeeded.
        platform: "google" or "meta".
        leads: CRM lead count for today (0 if not available).
        daily_budget: Daily budget for pacing (if None, fallback thresholds used).
        active_start: Active schedule start hour (default 9).
        active_end: Active schedule end hour (default 21). Use 0 and 23 for 24h campaigns.
        now: Override current time (defaults to IST now).

    Returns:
        {"api_health": {...}, "perf_health": {...}}
    """
    if now is None:
        now = _now_ist()

    last_sync = getattr(account, "last_sync_at", None)  # UTC datetime

    api_badge = compute_api_health(
        api_success=api_success,
        last_sync_at=last_sync,
        now=now,
        platform=platform,
    )

    perf_badge = compute_perf_health(
        api_success=api_success,
        campaign_active=bool(getattr(account, "is_live", False)),
        spend=float(getattr(account, "spend", 0) or 0),
        impressions=int(getattr(account, "impressions", 0) or 0),
        clicks=int(getattr(account, "clicks", 0) or 0),
        conversions=float(getattr(account, "conversions", 0) or 0),
        leads=int(leads or 0),
        ctr=float(getattr(account, "ctr", 0) or 0),
        cpa=float(getattr(account, "cpa", 0) or 0),
        target_cpa=getattr(account, "target_cpa", None),
        daily_budget=daily_budget,
        active_start=active_start,
        active_end=active_end,
        now=now,
    )

    return {"api_health": api_badge, "perf_health": perf_badge}