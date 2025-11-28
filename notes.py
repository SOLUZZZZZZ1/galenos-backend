# notes.py — Notas clínicas del médico

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from auth import get_current_user
from database import get_db
import crud
from schemas import ClinicalNoteCreate, ClinicalNoteReturn

router = APIRouter(prefix="/notes", tags=["Clinical Notes"])


@router.post("/{patient_id}", response_model=ClinicalNoteReturn)
def create_note(
    patient_id: int,
    data: ClinicalNoteCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado.")

    return crud.create_clinical_note(db, patient_id, current_user.id, data)


@router.get("/{patient_id}", response_model=list[ClinicalNoteReturn])
def list_notes(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado.")

    return crud.get_notes_for_patient(db, patient_id)
