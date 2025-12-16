# community_router.py — Módulo Comunidad (formativo)
# SAFE: independiente de Guardia y Pacientes
# Endpoints v1: listar, crear caso, ver caso, responder

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import datetime
from typing import Optional

from database import get_db
from auth import get_current_user
from models import CommunityCase, CommunityResponse, DoctorProfile
from pydantic import BaseModel, Field

router = APIRouter(prefix="/community", tags=["community"])


# ======================
# Schemas
# ======================
class CommunityCaseCreateIn(BaseModel):
    title: Optional[str] = None
    clinical_context: Optional[str] = None
    question: Optional[str] = None
    visibility: Optional[str] = Field("public", description="public | private")


class CommunityResponseCreateIn(BaseModel):
    content: str


# ======================
# Helpers
# ======================
def _now():
    return datetime.utcnow()


def _get_guard_alias(db: Session, user_id: int) -> str:
    dp = db.query(DoctorProfile).filter(DoctorProfile.user_id == user_id).first()
    return (dp.guard_alias if dp and dp.guard_alias else None) or "anónimo"


def _get_visible_case_or_404(db: Session, case_id: int, current_user_id: int) -> CommunityCase:
    c = db.query(CommunityCase).filter(CommunityCase.id == case_id).first()
    if not c:
        raise HTTPException(404, "Not Found")

    # Visible si es tuyo o es público
    vis = (c.visibility or "public")
    if c.user_id != current_user_id and vis != "public":
        raise HTTPException(404, "Not Found")

    return c


# ======================
# GET /community/cases
# ======================
@router.get("/cases")
def list_cases(
    status: Optional[str] = Query("open"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(CommunityCase).filter(
        or_(
            CommunityCase.user_id == current_user.id,
            CommunityCase.visibility == "public",
        )
    )

    if status and status != "all":
        q = q.filter(CommunityCase.status == status)

    cases = q.order_by(CommunityCase.last_activity_at.desc()).all()

    return {
        "items": [
            {
                "id": c.id,
                "title": c.title or "Caso sin título",
                "clinical_context": c.clinical_context or "",
                "question": c.question or "",
                "status": c.status or "open",
                "visibility": c.visibility or "public",
                "created_at": c.created_at,
                "last_activity_at": c.last_activity_at,
                "is_owner": (c.user_id == current_user.id),
            }
            for c in cases
        ]
    }


# ======================
# POST /community/cases
# ======================
@router.post("/cases")
def create_case(
    payload: CommunityCaseCreateIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not any(
        [
            (payload.title or "").strip(),
            (payload.clinical_context or "").strip(),
            (payload.question or "").strip(),
        ]
    ):
        raise HTTPException(400, "Contenido vacío")

    visibility = payload.visibility if payload.visibility in ["public", "private"] else "public"

    case = CommunityCase(
        user_id=current_user.id,
        title=(payload.title or "").strip(),
        clinical_context=(payload.clinical_context or "").strip(),
        question=(payload.question or "").strip(),
        visibility=visibility,
        status="open",
        created_at=_now(),
        last_activity_at=_now(),
    )

    db.add(case)
    db.commit()
    db.refresh(case)

    return {"id": case.id}


# ======================
# GET /community/cases/{id}
# ======================
@router.get("/cases/{case_id}")
def get_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    c = _get_visible_case_or_404(db, case_id, current_user.id)

    responses = (
        db.query(CommunityResponse)
        .filter(CommunityResponse.case_id == c.id)
        .order_by(CommunityResponse.id.asc())
        .all()
    )

    return {
        "case": {
            "id": c.id,
            "title": c.title or "",
            "clinical_context": c.clinical_context or "",
            "question": c.question or "",
            "status": c.status or "open",
            "visibility": c.visibility or "public",
            "created_at": c.created_at,
            "last_activity_at": c.last_activity_at,
            "is_owner": (c.user_id == current_user.id),
        },
        "responses": [
            {
                "id": r.id,
                "author_alias": r.author_alias or "anónimo",
                "content": r.content or "",
                "created_at": r.created_at,
            }
            for r in responses
        ],
    }


# ======================
# POST /community/cases/{id}/responses
# ======================
@router.post("/cases/{case_id}/responses")
def add_response(
    case_id: int,
    payload: CommunityResponseCreateIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    c = _get_visible_case_or_404(db, case_id, current_user.id)

    text = (payload.content or "").strip()
    if not text:
        raise HTTPException(400, "Contenido vacío")

    r = CommunityResponse(
        case_id=c.id,
        user_id=current_user.id,
        author_alias=_get_guard_alias(db, current_user.id),
        content=text,
        created_at=_now(),
    )

    db.add(r)

    c.last_activity_at = _now()
    db.add(c)

    db.commit()
    db.refresh(r)

    return {
        "id": r.id,
        "author_alias": r.author_alias or "anónimo",
        "content": r.content,
        "created_at": r.created_at,
    }
