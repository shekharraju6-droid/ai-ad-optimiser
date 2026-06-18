from fastapi import APIRouter
from backend.services.reports import get_full_report, get_savings_report, get_waste_breakdown, get_action_history

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/report/full")
def full_report():
    return get_full_report()


@router.get("/report/savings")
def savings_report():
    return get_savings_report()


@router.get("/report/waste")
def waste_report():
    return get_waste_breakdown()


@router.get("/report/actions")
def actions_report():
    return get_action_history()
