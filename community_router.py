# community_router.py — Módulo Comunidad (formativo + concurso semanal con cierre IA)
# SAFE: independiente de Guardia y Pacientes
# Endpoints:
# - GET  /community/cases
# - POST /community/cases
# - GET  /community/cases/{case_id}
# - POST /community/cases/{case_id}/responses
# - POST /community/cases/{case_id}/close-with-ai  (ADMIN_TOKEN + IA resumen + cierre)

import os
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import datetime
from typing import Optional

from database import get_db
from auth import get_current_user
from models import CommunityCase, CommunityResponse, DoctorProfile
from pydantic import BaseModel, Field

from openai import OpenAI

router = APIRouter(prefix="/community", tags=["community"])


# ======================
# CONFIG / ADMIN TOKEN
# ======================
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN") or "GalenosAdminToken@123"

def _admin_auth(x_admin_token: str | None):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "Unauthorized")


# ======================
# PROMPT IA (Concurso semanal)
# ======================
AI_SUMMARY_PROMPT = """
Actúa como editor clínico formativo de Galenos.

Resume las aportaciones realizadas por distintos médicos en el siguiente caso formativo.

Reglas obligatorias:
- NO des diagnóstico final.
- NO digas qué respuesta es correcta o incorrecta.
- NO utilices lenguaje prescriptivo (“hay que”, “se debe”, “recomendado”).
- NO menciones autores individuales.
- NO inventes información no presente en las respuestas.
- Mantén un tono neutral, formativo y profesional.

Estructura el resumen exactamente así:

🔒 Caso cerrado · Resumen Galenos

1. Prioridades iniciales comunes
2. Pruebas tempranas mencionadas
3. Enfoques de manejo inicial
4. Aprendizaje clave

Objetivo:
Facilitar aprendizaje colectivo, no resolver el caso.
"""


def _ai_generate_summary(full_case_text: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY") or ""
    if not api_key:
        raise HTTPException(500, "Falta OPENAI_API_KEY en el servidor.")

    client = OpenAI(api_key=api_key)

    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL") or "gpt-4.1-mini",
        messages=[
            {"role": "system", "content": AI_SUMMARY_PROMPT.strip()},
            {"role": "user", "content": full_case_text.strip()},
        ],
        temperature=0.2,
    )

    txt = (resp.choices[0].message.content or "").strip()
    if not txt:
        raise HTTPException(500, "La IA no devolvió contenido.")
    return txt


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
# GET /community/cases/{case_id}
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
# POST /community/cases/{case_id}/responses
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


# ======================
# POST /community/cases/{case_id}/close-with-ai
# (ADMIN_TOKEN) Cierra el caso + genera resumen IA + lo publica como "Galenos"
# ======================
@router.post("/cases/{case_id}/close-with-ai")
def close_case_with_ai(
    case_id: int,
    x_admin_token: str | None = Header(None),
    db: Session = Depends(get_db),
):
    _admin_auth(x_admin_token)

    case = db.query(CommunityCase).filter(CommunityCase.id == case_id).first()
    if not case:
        raise HTTPException(404, "Not Found")

    if (case.status or "open") == "closed":
        return {"ok": True, "status": "closed", "message": "El caso ya estaba cerrado."}

    responses = (
        db.query(CommunityResponse)
        .filter(CommunityResponse.case_id == case.id)
        .order_by(CommunityResponse.id.asc())
        .all()
    )

    full_case_text = (
        f"CASO:\n"
        f"Título: {case.title}\n"
        f"Contexto: {case.clinical_context}\n"
        f"Pregunta: {case.question}\n\n"
        "RESPUESTAS:\n"
        + (
            "\n".join(f"- {r.content}" for r in responses if r.content)
            or "- (Sin respuestas de participantes todavía.)"
        )
    )

    summary = _ai_generate_summary(full_case_text)

    final_response = CommunityResponse(
        case_id=case.id,
        user_id=case.user_id,
        author_alias="Galenos",
        content=summary,
        created_at=_now(),
    )
    db.add(final_response)

    case.status = "closed"
    case.last_activity_at = _now()
    if not (case.title or "").startswith("🔒"):
        case.title = f"🔒 {case.title}"

    db.add(case)
    db.commit()
    db.refresh(final_response)

    return {"ok": True, "status": "closed", "summary_response_id": final_response.id}
