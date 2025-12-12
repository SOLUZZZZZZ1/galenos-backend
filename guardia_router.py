# guardia_router.py — De Guardia (con adjuntos clínicos anonimizados)
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
import re

from database import get_db
from auth import get_current_user
from models import GuardCase, GuardMessage, Analytic, Imaging

router = APIRouter(prefix="/guard", tags=["guardia"])


# ======================================================
# Anonimización básica (sin cifrado para GuardCase)
# ======================================================
def anonimize_text(text: str) -> str:
    text = (text or "").strip()
    clean = text
    clean = re.sub(r"\b[\w\.-]+@[\w\.-]+\.\w+\b", "[email]", clean)
    clean = re.sub(r"\b\d{9}\b", "[teléfono]", clean)
    clean = re.sub(r"\b\d{7,8}[A-Za-z]\b", "[documento]", clean)
    clean = re.sub(r"\b\d{12,}\b", "[id]", clean)
    return clean.strip()


# ======================================================
# Schemas locales
# ======================================================
class GuardAttachment(BaseModel):
    kind: str  # "analytic" | "imaging"
    id: int


class GuardCaseCreateIn(BaseModel):
    title: str
    original: str
    patient_id: Optional[int] = None
    author_alias: Optional[str] = None
    age_group: Optional[str] = None
    sex: Optional[str] = None
    context: Optional[str] = None
    attachments: Optional[List[GuardAttachment]] = None


class GuardMessageCreateIn(BaseModel):
    author_alias: str
    content: str


# ======================================================
# Adjuntos disponibles (anonimizados)
# ======================================================
@router.get("/attachments/options")
def guard_attachment_options(
    patient_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
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

    imaging_items = []
    for i in imaging:
        img_type = (
            getattr(i, "img_type", None)
            or getattr(i, "type", None)
            or getattr(i, "study_type", None)
            or "imagen"
        )
        imaging_items.append(
            {"id": i.id, "type": img_type, "summary": getattr(i, "summary", "") or ""}
        )

    return {
        "analytics": [
            {"id": a.id, "exam_date": a.exam_date, "summary": a.summary or ""}
            for a in analytics
        ],
        "imaging": imaging_items,
    }


# ======================================================
# LISTAR CASOS
# ======================================================
@router.get("/cases")
def list_guard_cases(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(GuardCase)

    if status:
        q = q.filter(GuardCase.status == status)

    q = q.order_by(GuardCase.last_activity_at.desc().nullslast(), GuardCase.id.desc())
    cases = q.all()

    items = []
    for c in cases:
        msg_count = (
            db.query(func.count(GuardMessage.id))
            .filter(GuardMessage.case_id == c.id)
            .scalar()
        ) or 0

        first_msg = (
            db.query(GuardMessage)
            .filter(GuardMessage.case_id == c.id)
            .order_by(GuardMessage.id.asc())
            .first()
        )
        author_alias = first_msg.author_alias if first_msg else "anónimo"

        items.append(
            {
                "id": c.id,
                "title": c.title,
                "anonymized_summary": c.anonymized_summary,
                "author_alias": author_alias,
                "status": c.status,
                "message_count": msg_count,
                "last_activity_at": c.last_activity_at,
                "is_favorite": False,
                "age_group": c.age_group,
                "sex": c.sex,
                "context": c.context,
            }
        )

    return {"items": items}


# ======================================================
# DETALLE DE CASO
# ======================================================
@router.get("/cases/{case_id}")
def get_guard_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    c = db.query(GuardCase).filter(GuardCase.id == case_id).first()
    if not c:
        raise HTTPException(404, "Caso no encontrado.")

    return {
        "id": c.id,
        "title": c.title,
        "anonymized_summary": c.anonymized_summary,
        "status": c.status,
        "age_group": c.age_group,
        "sex": c.sex,
        "context": c.context,
        "created_at": c.created_at,
        "last_activity_at": c.last_activity_at,
    }


# ======================================================
# MENSAJES DE UN CASO
# ======================================================
@router.get("/cases/{case_id}/messages")
def list_case_messages(
    case_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    msgs = (
        db.query(GuardMessage)
        .filter(GuardMessage.case_id == case_id)
        .order_by(GuardMessage.created_at.asc().nullslast(), GuardMessage.id.asc())
        .all()
    )

    return {
        "items": [
            {
                "id": m.id,
                "author_alias": m.author_alias,
                "clean_content": m.clean_content,
                "moderation_status": m.moderation_status,
                "created_at": m.created_at,
            }
            for m in msgs
        ]
    }


# ======================================================
# AÑADIR MENSAJE A UN CASO
# ======================================================
@router.post("/cases/{case_id}/messages")
def create_case_message(
    case_id: int,
    payload: GuardMessageCreateIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    c = db.query(GuardCase).filter(GuardCase.id == case_id).first()
    if not c:
        raise HTTPException(404, "Caso no encontrado.")

    clean_text = anonimize_text(payload.content)

    msg = GuardMessage(
        case_id=case_id,
        author_alias=payload.author_alias or "anónimo",
        clean_content=clean_text,
        moderation_status="ok",
        created_at=datetime.utcnow(),
    )
    db.add(msg)

    c.last_activity_at = datetime.utcnow()
    db.add(c)

    db.commit()
    db.refresh(msg)

    return {
        "id": msg.id,
        "author_alias": msg.author_alias,
        "clean_content": msg.clean_content,
        "moderation_status": msg.moderation_status,
        "created_at": msg.created_at,
    }


# ======================================================
# CREAR CASO (con adjuntos opcionales)
# ======================================================
@router.post("/cases")
def create_guard_case(
    payload: GuardCaseCreateIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    original_text = (payload.original or "").strip()

    # Adjuntos seleccionados
    if payload.attachments:
        blocks = []
        for att in payload.attachments:
            if att.kind == "analytic":
                a = db.query(Analytic).filter(Analytic.id == att.id).first()
                if a:
                    blocks.append(
                        f"ANALÍTICA ({a.exam_date or 'fecha no especificada'}):\n{a.summary or ''}"
                    )
            elif att.kind == "imaging":
                i = db.query(Imaging).filter(Imaging.id == att.id).first()
                if i:
                    img_type = (
                        getattr(i, "img_type", None)
                        or getattr(i, "type", None)
                        or getattr(i, "study_type", None)
                        or "imagen"
                    )
                    blocks.append(
                        f"IMAGEN ({img_type}):\n{getattr(i, 'summary', '') or ''}"
                    )

        if blocks:
            original_text += (
                "\n\nADJUNTOS CLÍNICOS (ANONIMIZADOS):\n" + "\n\n".join(blocks)
            )

    clean_text = anonimize_text(original_text)

    # ⚠️ GuardCase NO admite original_encrypted → NO lo pasamos
    case = GuardCase(
        title=payload.title,
        anonymized_summary=clean_text,
        author_id=current_user.id,
        patient_id=payload.patient_id,
        status="open",
        age_group=payload.age_group,
        sex=payload.sex,
        context=payload.context,
        last_activity_at=datetime.utcnow(),
    )

    db.add(case)
    db.commit()
    db.refresh(case)

    # Primer mensaje
    msg = GuardMessage(
        case_id=case.id,
        author_alias=payload.author_alias or "anónimo",
        clean_content=clean_text,
        moderation_status="ok",
        created_at=datetime.utcnow(),
    )
    db.add(msg)
    db.commit()

    return case
