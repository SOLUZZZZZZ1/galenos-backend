# weekly_contest_router.py — Automatización concurso semanal (Lunes → Lunes)
# Endpoint: POST /admin/weekly-contest/run
# - Cierra el concurso semanal abierto con IA
# - Publica el nuevo concurso semanal (especialidad rotativa)
# - Protegido por ADMIN_TOKEN
# - Idempotente (no duplica)

import os
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import and_

from database import get_db
from models import CommunityCase, CommunityResponse
from community_router import _ai_generate_summary, _now  # reutilizamos lo ya probado
from openai import OpenAI

router = APIRouter(prefix="/admin/weekly-contest", tags=["admin-weekly-contest"])

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN") or "GalenosAdminToken@123"

def _admin_auth(x_admin_token: str | None):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "Unauthorized")


# ----------------------
# Rotación de especialidades (determinista por semana ISO)
# ----------------------
SPECIALTIES: List[str] = [
    "Urgencias",
    "Medicina Interna",
    "Cardiología",
    "Neumología",
    "Radiología",
    "Analíticas",
    "Neurología",
    "Geriatría",
]

def _current_specialty_by_week() -> str:
    week = datetime.utcnow().isocalendar().week
    return SPECIALTIES[(week - 1) % len(SPECIALTIES)]


# ----------------------
# Prompt IA para crear el caso semanal
# ----------------------
CASE_CREATION_PROMPT = """
Actúa como editor clínico formativo de Galenos.

Crea un CASO FORMATIVO SEMANAL para médicos de la especialidad indicada.

Reglas:
- NO incluyas datos identificativos.
- NO des diagnóstico final.
- NO prescribas tratamientos.
- El objetivo es fomentar debate clínico, no resolver el caso.

Devuelve EXACTAMENTE este formato (sin markdown):

TÍTULO:
<un título claro y atractivo>

CONTEXTO:
<breve contexto clínico, 3–5 líneas>

PREGUNTA:
<una pregunta clara tipo “¿Qué harías tú en los primeros minutos?”>
"""

def _ai_generate_weekly_case(specialty: str) -> dict:
    api_key = os.getenv("OPENAI_API_KEY") or ""
    if not api_key:
        raise HTTPException(500, "Falta OPENAI_API_KEY")

    client = OpenAI(api_key=api_key)

    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL") or "gpt-4.1-mini",
        messages=[
            {"role": "system", "content": CASE_CREATION_PROMPT.strip()},
            {"role": "user", "content": f"ESPECIALIDAD: {specialty}"},
        ],
        temperature=0.4,
    )

    text = (resp.choices[0].message.content or "").strip()
    if not text:
        raise HTTPException(500, "La IA no devolvió el caso semanal.")

    # Parseo simple y robusto
    out = {"title": "", "context": "", "question": ""}
    section = None
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("TÍTULO"):
            section = "title"; continue
        if line.upper().startswith("CONTEXTO"):
            section = "context"; continue
        if line.upper().startswith("PREGUNTA"):
            section = "question"; continue
        if section and line:
            out[section] += (line + " ")

    return {
        "title": out["title"].strip() or f"Concurso semanal · {specialty}",
        "clinical_context": out["context"].strip(),
        "question": out["question"].strip(),
    }


# ----------------------
# Endpoint principal
# ----------------------
@router.post("/run")
def run_weekly_contest(
    x_admin_token: str | None = Header(None),
    db: Session = Depends(get_db),
):
    _admin_auth(x_admin_token)

    # 1) Cerrar concurso semanal abierto (si existe)
    open_weekly = (
        db.query(CommunityCase)
        .filter(
            and_(
                CommunityCase.status == "open",
                CommunityCase.title.ilike("Concurso semanal%")
            )
        )
        .order_by(CommunityCase.created_at.desc())
        .first()
    )

    if open_weekly:
        responses = (
            db.query(CommunityResponse)
            .filter(CommunityResponse.case_id == open_weekly.id)
            .order_by(CommunityResponse.id.asc())
            .all()
        )

        full_case_text = (
            f"CASO:\n"
            f"Título: {open_weekly.title}\n"
            f"Contexto: {open_weekly.clinical_context}\n"
            f"Pregunta: {open_weekly.question}\n\n"
            "RESPUESTAS:\n"
            + (
                "\n".join(f"- {r.content}" for r in responses if r.content)
                or "- (Sin respuestas de participantes todavía.)"
            )
        )

        summary = _ai_generate_summary(full_case_text)

        final_msg = CommunityResponse(
            case_id=open_weekly.id,
            user_id=open_weekly.user_id,
            author_alias="Galenos",
            content=summary,
            created_at=_now(),
        )
        db.add(final_msg)

        open_weekly.status = "closed"
        open_weekly.last_activity_at = _now()
        if not open_weekly.title.startswith("🔒"):
            open_weekly.title = f"🔒 {open_weekly.title}"

        db.add(open_weekly)
        db.commit()

    # 2) Publicar nuevo concurso semanal (ANTI-DUPLICADOS)
week = datetime.utcnow().isocalendar().week
specialty = _current_specialty_by_week()

# 🔒 Guardarraíl: si ya existe concurso de esta semana, NO crear otro
existing = (
    db.query(CommunityCase)
    .filter(
        CommunityCase.title.ilike(f"Concurso semanal · Semana {week}%")
    )
    .first()
)

if existing:
    return {
        "ok": True,
        "closed_previous": bool(open_weekly),
        "new_case_id": existing.id,
        "specialty": specialty,
        "week": week,
        "note": "Concurso semanal ya existente. No se creó uno nuevo."
    }

case_data = _ai_generate_weekly_case(specialty)

new_case = CommunityCase(
    user_id=1,  # usuario sistema / Galenos
    title=f"Concurso semanal · Semana {week} · {specialty}",
    clinical_context=case_data["clinical_context"],
    question=case_data["question"],
    visibility="public",
    status="open",
    created_at=_now(),
    last_activity_at=_now(),
)

db.add(new_case)
db.commit()
db.refresh(new_case)
