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
# Anonimización simple
# ======================================================
def anonimize_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\b[\w\.-]+@[\w\.-]+\.\w+\b", "[email]", text)
    text = re.sub(r"\b\d{9}\b", "[teléfono]", text)
    text = re.sub(r"\b\d{7,8}[A-Za-z]\b", "[documento]", text)
    text = re.sub(r"\b\d{12,}\b", "[id]", text)
    return text.strip()


# ======================================================
# Schemas
# ======================================================
class GuardAttachment(BaseModel):
    kind: str   # "analytic" | "imaging"
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
# Adjuntos disponibles
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

    return {
        "analytics": [
            {"id": a.id, "exam_date": a.exam_date, "summary": a.summary or ""}
            for a in analytics
        ],
        "imaging": [
            {
                "id": i.id,
                "type": i.type or "imagen",
                "summary": i.summary or "",
            }
            for i in imaging
        ],
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
    q = db.query(GuardCase).filter(GuardCase.user_id == current_user.id)

    if status:
        q = q.filter(GuardCase.status == status)

    q = q.order_by(GuardCase.last_activity_at.desc())

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

        items.append(
            {
                "id": c.id,
                "title": c.title,
                "anonymized_summary": c.anonymized_summary,
                "author_alias": first_msg.author_alias if first_msg else "anónimo",
                "status": c.status,
                "message_count": msg_count,
                "last_activity_at": c.last_activity_at,
                "age_group": c.age_group,
                "sex": c.sex,
                "context": c.context,
            }
        )

    return {"items": items}


# ======================================================
# CREAR CASO
# ======================================================
@router.post("/cases")
def create_guard_case(
    payload: GuardCaseCreateIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    original_text = payload.original or ""

    # Adjuntar resúmenes
    if payload.attachments:
        blocks = []
        for att in payload.attachments:
            if att.kind == "analytic":
                a = db.query(Analytic).filter(Analytic.id == att.id).first()
                if a:
                    blocks.append(f"ANALÍTICA:\n{a.summary or ''}")
            elif att.kind == "imaging":
                i = db.query(Imaging).filter(Imaging.id == att.id).first()
                if i:
                    blocks.append(f"IMAGEN ({i.type or 'imagen'}):\n{i.summary or ''}")

        if blocks:
            original_text += "\n\n" + "\n\n".join(blocks)

    clean_text = anonimize_text(original_text)

    case = GuardCase(
        user_id=current_user.id,
        title=payload.title,
        anonymized_summary=clean_text,
        status="open",
        patient_ref_id=payload.patient_id,
        age_group=payload.age_group,
        sex=payload.sex,
        context=payload.context,
        last_activity_at=datetime.utcnow(),
    )

    db.add(case)
    db.commit()
    db.refresh(case)

    msg = GuardMessage(
        case_id=case.id,
        user_id=current_user.id,
        author_alias=payload.author_alias or "anónimo",
        raw_content=original_text,
        clean_content=clean_text,
        moderation_status="ok",
        created_at=datetime.utcnow(),
    )

    db.add(msg)
    db.commit()

    return case
