# guardia_router.py — Módulo De Guardia con adjuntos clínicos anonimizados

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any

from database import get_db
from auth import get_current_user
from models import GuardCase, GuardMessage, Analytic, Imaging
from schemas import GuardCaseCreate
from utils_guardia import moderate_and_anonimize

router = APIRouter(prefix="/guard", tags=["guardia"])


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
    Devuelve analíticas e imágenes disponibles para adjuntar
    (solo texto clínico, sin ficheros).
    """
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
                "type": i.img_type,
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
    payload: GuardCaseCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Crea una consulta de guardia.
    Puede incluir adjuntos clínicos anonimizados (analíticas / imágenes).
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
                    f"ANALÍTICA ({a.exam_date or 'fecha no especificada'}):\n{a.summary}"
                )

            if att.kind == "imaging":
                i = db.query(Imaging).filter(Imaging.id == att.id).first()
                if not i:
                    continue
                blocks.append(
                    f"IMAGEN ({i.img_type}):\n{i.summary}"
                )

        if blocks:
            original_text += "\n\nADJUNTOS CLÍNICOS (ANONIMIZADOS):\n" + "\n\n".join(blocks)

    # ==========================
    # Anonimización y moderación
    # ==========================
    clean = moderate_and_anonimize(original_text)

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

    msg = GuardMessage(
        case_id=case.id,
        author_alias=payload.author_alias,
        clean_content=clean["clean_content"],
        moderation_status=clean["moderation_status"],
    )
    db.add(msg)
    db.commit()

    return case
