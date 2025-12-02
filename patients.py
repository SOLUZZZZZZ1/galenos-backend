# patients.py — Endpoints de pacientes

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from auth import get_current_user
from database import get_db
from schemas import PatientCreate, PatientReturn, PatientUpdate
import crud

router = APIRouter(prefix="/patients", tags=["Patients"])


@router.post("/", response_model=PatientReturn)
def create_patient(
    data: PatientCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    return crud.create_patient(db, doctor_id=current_user.id, data=data)


@router.get("/", response_model=list[PatientReturn])
def list_patients(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    return crud.get_patients_for_doctor(db, doctor_id=current_user.id)


@router.get("/{patient_id}", response_model=PatientReturn)
def get_patient_detail(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)

    if not patient:
        raise HTTPException(404, "Paciente no encontrado o no pertenece al usuario.")

    return patient


@router.put("/{patient_id}", response_model=PatientReturn)
def update_patient_detail(
    patient_id: int,
    data: PatientUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado o no pertenece al usuario.")

    updated = crud.update_patient(db, patient, data)
    return updated
