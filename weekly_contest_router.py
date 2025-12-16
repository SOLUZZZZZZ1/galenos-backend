# weekly_contest_router.py — Automatización concurso semanal (Lunes → Lunes)
# Endpoint: POST /admin/weekly-contest/run
# - Cierra el concurso semanal abierto con IA
# - Publica el nuevo concurso semanal (especialidad rotativa)
# - Protegido por ADMIN_TOKEN
# - Idempotente (anti-duplicados por semana ISO)

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


def _current_specialty_by_week(week: int) -> str:
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

    out = {"title": "", "context": "", "question": ""}
    section = None

    for line in text.splitlines():
        line = (line or "").strip()

        if line.upper().startswith("TÍTULO"):
            section = "title"
            continue
        if line.upper().startswith("CONTEXTO"):
            section = "context"
            continue
        if line.upper().startswith("PREGUNTA"):
            section = "question"
            continue

        if section and line:
            out[section] += (line + " ")

    return {
        "title": (out["title"].strip() or f"Concurso semanal · {specialty}"),
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

    # Semana ISO actual (UTC)
    week = datetime.utcnow().isocalendar().week
    specialty = _current_specialty_by_week(week)

    # ✅ ANTI-DUPLICADOS: si ya existe concurso semanal para esta semana, no creamos otro
    existing = (
        db.query(CommunityCase)
        .filter(CommunityCase.title.ilike(f"Concurso semanal · Semana {week}%"))
        .order_by(CommunityCase.created_at.desc())
        .first()
    )
    if existing:
        # Aun así, intentamos cerrar el anterior si quedó abierto de semanas previas (sin crear nada nuevo)
        # (Opcional: si prefieres no tocar nada aquí, lo quitamos.)
        open_prev = (
            db.query(CommunityCase)
            .filter(
                and_(
                    CommunityCase.status == "open",
                    CommunityCase.title.ilike("Concurso semanal%"),
                    CommunityCase.id != existing.id,
                )
            )
            .order_by(CommunityCase.created_at.desc())
            .first()
        )

        closed_previous = False
        if open_prev:
            _close_case_with_ai(db, open_prev)
            closed_previous = True

        return {
            "ok": True,
            "closed_previous": closed_previous,
            "new_case_id": existing.id,
            "specialty": specialty,
            "week": week,
            "note": "Concurso semanal ya existente. No se creó uno nuevo.",
        }

    # 1) Cerrar concurso semanal abierto (si existe) — el más reciente
    open_weekly = (
        db.query(CommunityCase)
        .filter(
            and_(
                CommunityCase.status == "open",
                CommunityCase.title.ilike("Concurso semanal%"),
            )
        )
        .order_by(CommunityCase.created_at.desc())
        .first()
    )

    closed_previous = False
    if open_weekly:
        _close_case_with_ai(db, open_weekly)
        closed_previous = True

    # 2) Crear nuevo concurso semanal
    case_data = _ai_generate_weekly_case(specialty)

    new_case = CommunityCase(
        user_id=1,  # usuario “sistema” (si quieres lo hacemos configurable)
        title=f"Concurso semanal · Semana {week} · {specialty}",
        clinical_context=case_data.get("clinical_context") or "",
        question=case_data.get("question") or "",
        visibility="public",
        status="open",
        created_at=_now(),
        last_activity_at=_now(),
    )

    db.add(new_case)
    db.commit()
    db.refresh(new_case)

    return {
        "ok": True,
        "closed_previous": closed_previous,
        "new_case_id": new_case.id,
        "specialty": specialty,
        "week": week,
    }


def _close_case_with_ai(db: Session, case: CommunityCase) -> None:
    """
    Cierra un caso de concurso semanal con resumen IA como "Galenos".
    """
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

    final_msg = CommunityResponse(
        case_id=case.id,
        user_id=case.user_id,
        author_alias="Galenos",
        content=summary,
        created_at=_now(),
    )
    db.add(final_msg)

    case.status = "closed"
    case.last_activity_at = _now()
    if not (case.title or "").startswith("🔒"):
        case.title = f"🔒 {case.title}"

    db.add(case)
    db.commit()
