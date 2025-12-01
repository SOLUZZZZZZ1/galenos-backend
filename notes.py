
# notes.py — Notas clínicas del médico · Galenos.pro
# Ahora con soporte para:
# - Crear notas vinculadas a un paciente
# - Listar notas por paciente
# - EDITAR notas existentes (título y contenido)

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from auth import get_current_user
from database import get_db
import crud
from schemas import ClinicalNoteCreate, ClinicalNoteReturn
from models import ClinicalNote  # usamos el modelo directamente para la edición

router = APIRouter(prefix="/notes", tags=["Clinical Notes"])


# ============================
# Crear nota clínica
# ============================

@router.post("/{patient_id}", response_model=ClinicalNoteReturn)
def create_note(
    patient_id: int,
    data: ClinicalNoteCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Crea una nueva nota clínica para un paciente concreto.

    El paciente debe pertenecer al médico actual.
    """
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado.")

    return crud.create_clinical_note(db, patient_id, current_user.id, data)


# ============================
# Listar notas de un paciente
# ============================

@router.get("/{patient_id}", response_model=list[ClinicalNoteReturn])
def list_notes(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Lista todas las notas clínicas de un paciente, en orden cronológico."""
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado.")

    return crud.get_notes_for_patient(db, patient_id)


# ============================
# Modelo para actualización
# ============================

class ClinicalNoteUpdate(BaseModel):
    """Datos para editar una nota clínica.

    Ambos campos son opcionales. Solo se actualizan los que vengan informados.
    """
    title: Optional[str] = None
    content: Optional[str] = None


# ============================
# Editar nota clínica existente
# ============================

@router.put("/note/{note_id}", response_model=ClinicalNoteReturn)
def update_note(
    note_id: int,
    data: ClinicalNoteUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Edita una nota clínica existente (título y/o contenido).

    Solo puede editarla el médico que la creó.
    """
    # Buscamos la nota asegurando que pertenezca al médico actual
    note = (
        db.query(ClinicalNote)
        .filter(
            ClinicalNote.id == note_id,
            ClinicalNote.doctor_id == current_user.id,
        )
        .first()
    )

    if not note:
        raise HTTPException(404, "Nota clínica no encontrada o no pertenece al usuario.")

    # Actualizamos campos si vienen informados
    if data.title is not None:
        note.title = data.title.strip()

    if data.content is not None:
        note.content = data.content.strip()

    db.commit()
    db.refresh(note)

    return note
