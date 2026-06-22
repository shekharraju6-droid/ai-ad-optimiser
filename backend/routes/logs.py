from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.db.models import PendingAction

router = APIRouter(prefix="/api", tags=["logs"])


@router.get("/logs")
def get_logs(db: Session = Depends(get_db)):
    actions = db.query(PendingAction).order_by(PendingAction.id.desc()).limit(200).all()
    return [
        {
            "time": (a.created_at.isoformat() if a.created_at else None),
            "type": "OPTIMIZATION",
            "message": f"{a.action_type} for {a.account.name if a.account else 'Unknown'} - {a.keyword or a.campaign_id or a.adset_id or 'n/a'} [{a.status}]",
        }
        for a in actions
    ]