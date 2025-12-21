from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import User
from auth import get_current_user
import crud

router = APIRouter(prefix="/patients", tags=["review-state"])

class ReviewStateOut(BaseModel):
    patient_id: int
    last_reviewed_at: str | None = None
    last_reviewed_analytic_id: int | None = None

class ReviewStateIn(BaseModel):
    last_reviewed_analytic_id: int | None = None

@router.get("/{patient_id}/review-state", response_model=ReviewStateOut)
def get_review_state(patient_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    p = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado")

    st = crud.get_review_state(db, current_user.id, patient_id)
    if not st:
        return ReviewStateOut(patient_id=patient_id, last_reviewed_at=None, last_reviewed_analytic_id=None)

    return ReviewStateOut(
        patient_id=patient_id,
        last_reviewed_at=st.last_reviewed_at.isoformat() if st.last_reviewed_at else None,
        last_reviewed_analytic_id=st.last_reviewed_analytic_id,
    )

@router.post("/{patient_id}/review-state", response_model=ReviewStateOut)
def mark_reviewed(payload: ReviewStateIn, patient_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    p = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado")

    st = crud.upsert_review_state(db, current_user.id, patient_id, payload.last_reviewed_analytic_id)

    return ReviewStateOut(
        patient_id=patient_id,
        last_reviewed_at=st.last_reviewed_at.isoformat() if st.last_reviewed_at else None,
        last_reviewed_analytic_id=st.last_reviewed_analytic_id,
    )
