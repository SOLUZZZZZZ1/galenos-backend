# patients.py — Endpoints de pacientes

from fastapi import APIRouter, Depends, HTTPException, Query
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
    current_user=Depends(get_current_user)
):
    return crud.create_patient(db, doctor_id=current_user.id, data=data)


@router.get("/", response_model=list[PatientReturn])
def list_patients(
    include_archived: bool = Query(False),
    archived_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return crud.get_patients_for_doctor(
        db,
        doctor_id=current_user.id,
        include_archived=include_archived,
        archived_only=archived_only,
    )


@router.get("/{patient_id}", response_model=PatientReturn)
def get_patient_detail(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
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
    current_user=Depends(get_current_user)
):
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado o no pertenece al usuario.")

    updated = crud.update_patient(db, patient, data)
    return updated


# ✅ Archive / Unarchive
@router.post("/{patient_id}/archive", response_model=PatientReturn)
def archive_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado o no pertenece al usuario.")

    return crud.archive_patient(db, patient)


@router.post("/{patient_id}/unarchive", response_model=PatientReturn)
def unarchive_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado o no pertenece al usuario.")

    return crud.unarchive_patient(db, patient)


# ✅ Hard delete (irreversible) — requires hard=true
@router.delete("/{patient_id}")
def delete_patient(
    patient_id: int,
    hard: bool = Query(False),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    if not hard:
        raise HTTPException(400, "Borrado permanente requiere hard=true")

    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado o no pertenece al usuario.")

    try:
        crud.delete_patient_permanently(db, patient, doctor_id=current_user.id)
        return {"ok": True}
    except RuntimeError as e:
        # caso B2 falló -> no se tocó BD
        raise HTTPException(500, str(e))
    except Exception as e:
        raise HTTPException(500, f"Error borrando paciente: {e}")
