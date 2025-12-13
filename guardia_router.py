# guardia_router.py — De Guardia (ESTABLE A: sin adjuntos)
# - Alias siempre desde doctor_profile.guard_alias
# - Mensajes robustos
# - Sin rutas duplicadas ni variables inconsistentes

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional

from database import get_db
from auth import get_current_user
from models import GuardCase, GuardMessage, DoctorProfile

from pydantic import BaseModel

router = APIRouter(prefix="/guard", tags=["guardia"])


# ======================
# Schemas entrada
# ======================
class GuardCaseCreateIn(BaseModel):
    title: str
    content: str
    age_group: Optional[str] = None
    sex: Optional[str] = None
    context: Optional[str] = None


class GuardMessageCreateIn(BaseModel):
    content: str


# ======================
# Helpers
# ======================
def _get_guard_alias(db: Session, user_id: int) -> str:
    dp = db.query(DoctorProfile).filter(DoctorProfile.user_id == user_id).first()
    alias = (dp.guard_alias if dp and dp.guard_alias else None)
    return alias or "anónimo"


def _now():
    return datetime.utcnow()


# ======================
# Listar casos
# ======================
@router.get("/cases")
def list_cases(
    status: Optional[str] = Query("open"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(GuardCase).filter(GuardCase.user_id == current_user.id)
    if status:
        q = q.filter(GuardCase.status == status)

    cases = q.order_by(GuardCase.last_activity_at.desc()).all()

    items = []
    for c in cases:
        # primer mensaje para alias
        first_msg = (
            db.query(GuardMessage)
            .filter(GuardMessage.case_id == c.id)
            .order_by(GuardMessage.id.asc())
            .first()
        )
        author_alias = first_msg.author_alias if first_msg else _get_guard_alias(db, current_user.id)

        msg_count = (
            db.query(GuardMessage)
            .filter(GuardMessage.case_id == c.id)
            .count()
        )

        items.append(
            {
                "id": c.id,
                "title": c.title or "Consulta clínica sin título",
                "anonymized_summary": c.anonymized_summary or "",
                "author_alias": author_alias or "anónimo",
                "status": c.status or "open",
                "message_count": msg_count,
                "last_activity_at": c.last_activity_at,
                "age_group": c.age_group,
                "sex": c.sex,
                "context": c.context,
                "is_favorite": False,
            }
        )

    return {"items": items}


# ======================
# Detalle caso
# ======================
@router.get("/cases/{case_id}")
def get_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    c = (
        db.query(GuardCase)
        .filter(GuardCase.id == case_id, GuardCase.user_id == current_user.id)
        .first()
    )
    if not c:
        raise HTTPException(404, "Not Found")

    return {
        "id": c.id,
        "title": c.title or "Consulta clínica sin título",
        "anonymized_summary": c.anonymized_summary or "",
        "status": c.status or "open",
        "age_group": c.age_group,
        "sex": c.sex,
        "context": c.context,
        "created_at": c.created_at,
        "last_activity_at": c.last_activity_at,
    }


# ======================
# Listar mensajes
# ======================
@router.get("/cases/{case_id}/messages")
def list_messages(
    case_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    c = (
        db.query(GuardCase)
        .filter(GuardCase.id == case_id, GuardCase.user_id == current_user.id)
        .first()
    )
    if not c:
        raise HTTPException(404, "Not Found")

    msgs = (
        db.query(GuardMessage)
        .filter(GuardMessage.case_id == case_id)
        .order_by(GuardMessage.id.asc())
        .all()
    )

    return {
        "items": [
            {
                "id": m.id,
                "author_alias": m.author_alias or "anónimo",
                "clean_content": m.clean_content or "",
                "moderation_status": m.moderation_status or "ok",
                "created_at": m.created_at,
            }
            for m in msgs
        ]
    }


# ======================
# Crear caso (crea 1er mensaje)
# ======================
@router.post("/cases")
def create_case(
    payload: GuardCaseCreateIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    alias = _get_guard_alias(db, current_user.id)
    content = (payload.content or "").strip()
    if not content:
        raise HTTPException(400, "Contenido vacío")

    # Caso
    case = GuardCase(
        user_id=current_user.id,
        title=(payload.title or "").strip() or "Consulta clínica sin título",
        anonymized_summary=content,
        status="open",
        patient_ref_id=None,
        age_group=payload.age_group,
        sex=payload.sex,
        context=payload.context,
        created_at=_now(),
        last_activity_at=_now(),
    )
    db.add(case)
    db.commit()
    db.refresh(case)

    # Primer mensaje
    msg = GuardMessage(
        case_id=case.id,
        user_id=current_user.id,
        author_alias=alias,
        raw_content=content,
        clean_content=content,
        moderation_status="ok",
        created_at=_now(),
    )
    db.add(msg)
    db.commit()

    return {"id": case.id}


# ======================
# Añadir mensaje
# ======================
@router.post("/cases/{case_id}/messages")
def add_message(
    case_id: int,
    payload: GuardMessageCreateIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    c = (
        db.query(GuardCase)
        .filter(GuardCase.id == case_id, GuardCase.user_id == current_user.id)
        .first()
    )
    if not c:
        raise HTTPException(404, "Not Found")

    alias = _get_guard_alias(db, current_user.id)
    text = (payload.content or "").strip()
    if not text:
        raise HTTPException(400, "Contenido vacío")

    msg = GuardMessage(
        case_id=case_id,
        user_id=current_user.id,
        author_alias=alias,
        raw_content=text,
        clean_content=text,
        moderation_status="ok",
        created_at=_now(),
    )
    db.add(msg)

    c.last_activity_at = _now()
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
