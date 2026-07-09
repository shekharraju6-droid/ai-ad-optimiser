"""Interim Google Sheets route for Shyam Steel report formatting."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Account
from backend.services.sheets_connector import format_shyam_steel_sheet

router = APIRouter(prefix="/api/sheets", tags=["sheets"])


class SheetsFormatRequest(BaseModel):
    account_id: int
    spreadsheet_id: Optional[str] = None


@router.post("/format-shyam-steel")
def format_shyam_steel_report(req: SheetsFormatRequest, db: Session = Depends(get_db)):
    """Create or format a Google Sheet for Shyam Steel reports.

    Expects the account to have saved:
    - crm_credentials['gsheets_service_account'] or
    - credentials JSON containing gsheets_service_account

    If spreadsheet_id is not provided, a new spreadsheet is created.
    """
    account = db.query(Account).filter(Account.id == req.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.name != "Shyam Steel":
        raise HTTPException(status_code=400, detail="This interim endpoint is only for Shyam Steel")

    # Load service account JSON from stored integration config
    import json
    sa_json = None
    if account.crm_credentials:
        try:
            cfg = json.loads(account.crm_credentials) if isinstance(account.crm_credentials, str) else account.crm_credentials
            sa_json = cfg.get("gsheets_service_account")
        except Exception:
            pass
    if not sa_json and account.credentials:
        try:
            cfg = json.loads(account.credentials) if isinstance(account.credentials, str) else account.credentials
            sa_json = cfg.get("gsheets_service_account")
        except Exception:
            pass

    if not sa_json:
        raise HTTPException(
            status_code=400,
            detail="Google Sheets service account JSON not configured for Shyam Steel. Add it in Integrations."
        )

    try:
        result = format_shyam_steel_sheet(sa_json, req.spreadsheet_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google Sheets formatting failed: {e}")
