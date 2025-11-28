# timeline.py — Línea de tiempo clínica del paciente

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from auth import get_current_user
from database import get_db
import crud
from schemas import TimelineItemReturn

router = APIRouter(prefix="/timeline", tags=["Timeline"])


@router.get("/{patient_id}", response_model=list[TimelineItemReturn])
def get_timeline(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado.")

    return crud.get_timeline_for_patient(db, patient_id)
