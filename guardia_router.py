# guardia_router.py — Módulo De Guardia con adjuntos clínicos anonimizados (sin PDFs)
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List

from pydantic import BaseModel

from database import get_db
from auth import get_current_user
from models import GuardCase, GuardMessage, Analytic, Imaging
from utils_guardia import moderate_and_anonimize

router = APIRouter(prefix="/guard", tags=["guardia"])


# ======================================================
# Schemas locales (blindados)
# ======================================================
class GuardAttachment(BaseModel):
    kind: str  # "analytic" | "imaging"
    id: int


class GuardCaseCreateIn(BaseModel):
    title: str
    original: str
    patient_id: Optional[int] = None

    # campos opcionales (si tu front los manda, los guardamos; si no, no pasa nada)
    author_alias: Optional[str] = None
    age_group: Optional[str] = None
    sex: Optional[str] = None
    context: Optional[str] = None

    # NUEVO: adjuntos clínicos (anonimizados)
    attachments: Optional[List[GuardAttachment]] = None


# ======================================================
# NUEVO: opciones de adjuntos clínicos (anonimizados)
# ======================================================
@router.get("/attachments/options")
def guard_attachment_options(
    patient_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Devuelve analíticas e imágenes disponibles para adjuntar (texto clínico),
    sin ficheros originales.
    """
    # NOTA: aquí no aplicamos doctor_id porque tus tablas actuales se cuelgan de patient_id,
    # y el acceso del paciente ya lo controlas en tu flujo de pacientes.
    analytics = (
        db.query(Analytic)
        .filter(Analytic.patient_id == patient_id)
        .order_by(Analytic.exam_date.desc().nullslast(), Analytic.created_at.desc())
        .all()
    )

    imaging = (
        db.query(Imaging)
        .filter(Imaging.patient_id == patient_id)
        .order_by(Imaging.created_at.desc())
        .all()
    )

    return {
        "analytics": [
            {
                "id": a.id,
                "exam_date": a.exam_date,
                "summary": a.summary,
            }
            for a in analytics
        ],
        "imaging": [
            {
                "id": i.id,
                "type": i.img_type,  # en tu modelo Imaging usas img_type
                "summary": i.summary,
            }
            for i in imaging
        ],
    }


# ======================================================
# CREAR CASO DE GUARDIA (con adjuntos opcionales)
# ======================================================
@router.post("/cases")
def create_guard_case(
    payload: GuardCaseCreateIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Crea una consulta de guardia.
    Si hay attachments, se añaden como bloque "Adjuntos clínicos" antes de anonimizar.
    """

    original_text = payload.original or ""

    # ==========================
    # Adjuntos clínicos (opcional)
    # ==========================
    if payload.attachments:
        blocks = []
        for att in payload.attachments:
            if att.kind == "analytic":
                a = db.query(Analytic).filter(Analytic.id == att.id).first()
                if not a:
                    continue
                blocks.append(
                    f"ANALÍTICA ({a.exam_date or 'fecha no especificada'}):\n{a.summary or ''}"
                )

            elif att.kind == "imaging":
                i = db.query(Imaging).filter(Imaging.id == att.id).first()
                if not i:
                    continue
                blocks.append(
                    f"IMAGEN ({i.img_type or 'imagen'}):\n{i.summary or ''}"
                )

        if blocks:
            original_text += (
                "\n\nADJUNTOS CLÍNICOS (ANONIMIZADOS):\n" + "\n\n".join(blocks)
            )

    # ==========================
    # Anonimización y moderación
    # ==========================
    clean = moderate_and_anonimize(original_text)

    # GuardCase (usa el mismo patrón que tu backend ya tenía)
    case = GuardCase(
        title=payload.title,
        anonymized_summary=clean["clean_content"],
        original_encrypted=clean["encrypted_original"],
        author_id=current_user.id,
        patient_id=payload.patient_id,
        status="open",
        age_group=payload.age_group,
        sex=payload.sex,
        context=payload.context,
    )

    db.add(case)
    db.commit()
    db.refresh(case)

    # Primer mensaje
    msg = GuardMessage(
        case_id=case.id,
        author_alias=payload.author_alias or "anónimo",
        clean_content=clean["clean_content"],
        moderation_status=clean["moderation_status"],
    )
    db.add(msg)
    db.commit()

    return case
