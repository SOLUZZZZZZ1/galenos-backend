# pro_status_router.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from database import get_db
from models import User
from security import get_current_user  # tu actual dependencia de login

router = APIRouter(prefix="/me", tags=["me"])

@router.get("/pro-status")
def get_pro_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    now = datetime.utcnow()

    # Trial interno
    in_trial = False
    trial_days_left = 0

    if current_user.trial_end:
        if now < current_user.trial_end:
            in_trial = True
            trial_days_left = (current_user.trial_end - now).days

    return {
        "is_pro": bool(current_user.is_pro),
        "in_trial": in_trial,
        "trial_days_left": trial_days_left
    }
