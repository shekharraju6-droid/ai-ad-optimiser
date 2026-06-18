from fastapi import APIRouter
from backend.services.mock_db import mock_db

router = APIRouter(prefix="/api", tags=["logs"])


@router.get("/logs")
def get_logs():
    return mock_db.action_logs


@router.post("/reset-mock")
def reset_mock():
    mock_db.reset()
    return {"status": "success", "message": "Mock database reset successfully."}
