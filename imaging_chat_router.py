# imaging_chat_router.py — Q&A sobre imagen (orientativo) · Galenos
#
# Endpoints:
# - POST /imaging/{imaging_id}/ask   {"question": "..."}
# - POST /imaging/chat              {"imaging_id": 123, "question": "..."}  (compatibilidad)

from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from openai import OpenAI

from database import get_db
from auth import get_current_user
from models import Imaging, ImagingPattern, Patient, User

from prompts_imaging_chat import IMAGING_QA_SYSTEM_PROMPT

router = APIRouter(prefix="/imaging", tags=["Imaging-Chat"])


class ImagingAskIn(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)


class ImagingChatIn(BaseModel):
    # Compat: algunos frontends envían image_id en vez de imaging_id
    imaging_id: int | None = Field(None, ge=1)
    image_id: int | None = Field(None, ge=1)
    question: str = Field(..., min_length=2, max_length=500)


def _now_utc_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def _get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY") or ""
    if not api_key:
        raise HTTPException(500, "OPENAI_API_KEY no está configurada.")
    return OpenAI(api_key=api_key)


def _fetch_imaging_or_404(db: Session, imaging_id: int, doctor_id: int) -> Imaging:
    img = (
        db.query(Imaging)
        .join(Patient, Patient.id == Imaging.patient_id)
        .filter(Imaging.id == imaging_id, Patient.doctor_id == doctor_id)
        .first()
    )
    if not img:
        raise HTTPException(404, "Imagen no encontrada o no autorizada.")
    return img


def _fetch_patterns(db: Session, imaging_id: int) -> list[str]:
    rows = db.query(ImagingPattern.pattern_text).filter(ImagingPattern.imaging_id == imaging_id).all()
    out = []
    for (t,) in rows or []:
        s = (t or "").strip()
        if s:
            out.append(s)
    return out


def _build_context(img: Imaging, patterns: list[str]) -> str:
    exam = img.exam_date.isoformat() if getattr(img, "exam_date", None) else None
    created = img.created_at.isoformat() if getattr(img, "created_at", None) else None
    itype = (img.type or "").strip()

    summary = (img.summary or "").strip()
    differential = (img.differential or "").strip()

    ctx = [
        "ESTUDIO DE IMAGEN (datos internos Galenos)",
        f"Tipo: {itype or '—'}",
        f"Fecha (exam_date): {exam or '—'}",
        f"Alta registro: {created or '—'}",
        "",
        "Resumen radiológico (orientativo):",
        summary or "—",
        "",
        "Diagnóstico diferencial (orientativo):",
        differential or "—",
        "",
        "Patrones / hallazgos descritos:",
        ("- " + "\n- ".join(patterns)) if patterns else "—",
        "",
        "NOTA: Responde siguiendo las REGLAS del sistema.",
    ]
    return "\n".join(ctx)


def _ask_ai(question: str, ctx: str) -> str:
    client = _get_client()
    model = os.getenv("GALENOS_TEXT_MODEL") or os.getenv("GALENOS_CHAT_MODEL") or "gpt-4o-mini"

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": IMAGING_QA_SYSTEM_PROMPT},
                {"role": "user", "content": f"{ctx}\n\nPREGUNTA DEL MÉDICO:\n{question}\n\nResponde ahora."},
            ],
        )
        msg = resp.choices[0].message.content
        txt = (msg or "")
        if isinstance(txt, list) and txt:
            txt = str(getattr(txt[0], "text", "") or "")
        txt = str(txt).strip()
    except Exception as e:
        raise HTTPException(500, f"Error consultando IA: {e}")

    if not txt:
        raise HTTPException(500, "La IA no devolvió una respuesta válida.")
    return txt


@router.post("/{imaging_id}/ask")
def ask_about_imaging(
    imaging_id: int,
    payload: ImagingAskIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    img = _fetch_imaging_or_404(db, imaging_id, current_user.id)
    patterns = _fetch_patterns(db, img.id)
    ctx = _build_context(img, patterns)

    answer = _ask_ai((payload.question or "").strip(), ctx)

    return {
        "imaging_id": img.id,
        "answer": answer,
        "generated_at": _now_utc_str(),
        "disclaimer": "Orientativo. La interpretación final corresponde al médico responsable.",
    }


@router.post("/chat")
def imaging_chat_compat(
    payload: ImagingChatIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    imaging_id = payload.imaging_id or payload.image_id
    if not imaging_id:
        raise HTTPException(422, "Falta imaging_id")
    img = _fetch_imaging_or_404(db, int(imaging_id), current_user.id)
    patterns = _fetch_patterns(db, img.id)
    ctx = _build_context(img, patterns)

    answer = _ask_ai((payload.question or "").strip(), ctx)

    return {
        "imaging_id": img.id,
        "answer": answer,
        "generated_at": _now_utc_str(),
        "disclaimer": "Orientativo. La interpretación final corresponde al médico responsable.",
    }
