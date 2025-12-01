# analytics.py — Analíticas · IA real (Vision) para Galenos.pro
#
# Incluye:
# - /analytics/analyze        → IA "suelta" (no guarda en BD, modo sandbox)
# - /analytics/upload/{id}    → IA + guarda en BD + timeline para un paciente
# - /analytics/by-patient/{id}→ Lista analíticas históricas de un paciente
# - /analytics/chat           → Mini‑chat clínico sobre una analítica

import os
from typing import List, Optional, Any, Dict

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    HTTPException,
    Depends,
)
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from openai import OpenAI

from utils_pdf import convert_pdf_to_images
from utils_vision import analyze_with_ai_vision
from prompts_galenos import SYSTEM_PROMPT_GALENOS

from auth import get_current_user
from database import get_db
import crud
from schemas import AnalyticReturn

router = APIRouter(prefix="/analytics", tags=["Analytics"])


# =============================
# MODELOS AUXILIARES
# =============================

class ChatRequest(BaseModel):
    patient_alias: str
    file_name: Optional[str] = None
    markers: Optional[List[Dict[str, Any]]] = None
    summary: Optional[str] = None
    differential: Optional[str] = None
    question: str


def _build_status_and_range(
    value: Optional[float],
    ref_min: Optional[float],
    ref_max: Optional[float],
    unit: Optional[str],
) -> Dict[str, Optional[str]]:
    """Construye campos 'range' y 'status' para compatibilidad con el frontend.

    - range: texto tipo "12.0–16.0 g/dL"
    - status: "bajo" | "normal" | "elevado" | None
    """
    range_txt = None
    if ref_min is not None and ref_max is not None:
        if unit:
            range_txt = f"{ref_min}–{ref_max} {unit}"
        else:
            range_txt = f"{ref_min}–{ref_max}"

    status = None
    if value is not None and ref_min is not None and ref_max is not None:
        try:
            if value < ref_min:
                status = "bajo"
            elif value > ref_max:
                status = "elevado"
            else:
                status = "normal"
        except Exception:
            status = None

    return {"range": range_txt, "status": status}


def _prepare_images_from_file(file: UploadFile, content: bytes) -> List[str]:
    """Convierte el fichero subido en una lista de imágenes base64 para Vision."""
    ct = (file.content_type or "").lower()
    name_lower = file.filename.lower()
    images_b64: List[str] = []

    try:
        if "pdf" in ct or name_lower.endswith(".pdf"):
            images_b64 = convert_pdf_to_images(content)
        elif any(
            ext for ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff"]
            if name_lower.endswith(ext)
        ):
            import base64
            images_b64 = [base64.b64encode(content).decode("utf-8")]
        else:
            # Intentamos leerlo como PDF por si acaso
            images_b64 = convert_pdf_to_images(content)

        if not images_b64:
            raise HTTPException(
                status_code=400,
                detail="No se han podido extraer imágenes legibles de la analítica.",
            )
    except HTTPException:
        raise
    except Exception as e:
        print("[Analytics] Error preparando imágenes para Vision:", repr(e))
        raise HTTPException(
            status_code=500,
            detail="Error interno procesando la analítica."
        )

    return images_b64


def _call_vision_analytics(alias: str, images_b64: List[str]):
    """Llama a la IA Vision para analizar la analítica."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY no está configurada en el backend.",
        )

    model = os.getenv("GALENOS_VISION_MODEL", "gpt-4o")
    client = OpenAI(api_key=api_key)

    summary, differential_list, markers_raw = analyze_with_ai_vision(
        client=client,
        images_b64=images_b64,
        patient_alias=alias,
        model=model,
        system_prompt=SYSTEM_PROMPT_GALENOS,
    )
    return summary, differential_list, markers_raw


def _normalize_markers_for_front(markers_raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normaliza marcadores al formato esperado por el frontend actual."""
    markers: List[Dict[str, Any]] = []
    for m in markers_raw:
        name = str(m.get("name", "")).strip()
        if not name:
            continue

        raw_value = m.get("value", None)
        value_f: Optional[float] = None
        if isinstance(raw_value, (int, float)):
            value_f = float(raw_value)
        else:
            try:
                import re
                match = re.search(r"[-+]?[0-9]*\.?[0-9]+", str(raw_value))
                if match:
                    value_f = float(match.group())
            except Exception:
                value_f = None

        unit = m.get("unit")
        ref_min = m.get("ref_min")
        ref_max = m.get("ref_max")

        status_range = _build_status_and_range(value_f, ref_min, ref_max, unit)

        markers.append(
            {
                "name": name,
                "value": value_f,
                "unit": unit,
                "ref_min": ref_min,
                "ref_max": ref_max,
                "range": status_range["range"],
                "status": status_range["status"],
            }
        )
    return markers


# =====================================================
# 1) /analytics/analyze  (IA SIN guardar en BD)
# =====================================================

@router.post("/analyze")
async def analyze_lab_with_ai(
    alias: str = Form(..., description="Alias del paciente"),
    file: UploadFile = File(..., description="Analítica en PDF o imagen"),
):
    """Analiza una analítica (PDF/imagen) con IA (Vision) y devuelve resultado orientativo.

    - Soporta PDF multipágina.
    - Soporta imágenes (JPG/PNG, etc.).
    - NO guarda en BD. Modo 'sandbox' para el médico.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Fichero no válido")

    try:
        content = await file.read()
    except Exception:
        raise HTTPException(status_code=500, detail="No se pudo leer el fichero subido")

    if not content:
        raise HTTPException(status_code=400, detail="El fichero está vacío")

    images_b64 = _prepare_images_from_file(file, content)
    summary, differential_list, markers_raw = _call_vision_analytics(alias, images_b64)

    differential_text = "; ".join(differential_list) if differential_list else ""

    markers = _normalize_markers_for_front(markers_raw or [])

    return {
        "patient_alias": alias,
        "file_name": file.filename,
        "summary": summary,
        "differential": differential_text,
        "markers": markers,
    }


# =====================================================
# 2) /analytics/upload/{patient_id}  (IA + HISTÓRICO)
# =====================================================

@router.post("/upload/{patient_id}")
async def upload_analytic_for_patient(
    patient_id: int,
    alias: str = Form(..., description="Alias del paciente para el prompt"),
    file: UploadFile = File(..., description="Analítica en PDF o imagen"),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """Analiza una analítica con IA y la guarda como histórico del paciente.

    - Verifica que el paciente pertenece al médico.
    - Llama a la misma IA que /analyze.
    - Crea Analytic + marcadores + entrada en Timeline.
    """
    # 1) Comprobar paciente
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado o no pertenece al usuario.")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Fichero no válido")

    try:
        content = await file.read()
    except Exception:
        raise HTTPException(status_code=500, detail="No se pudo leer el fichero subido")

    if not content:
        raise HTTPException(status_code=400, detail="El fichero está vacío")

    # 2) Preparar imágenes
    images_b64 = _prepare_images_from_file(file, content)

    # 3) Llamar a IA
    summary, differential_list, markers_raw = _call_vision_analytics(alias, images_b64)

    # 4) Guardar Analytic en BD (differential como lista/JSON)
    analytic = crud.create_analytic(
        db=db,
        patient_id=patient_id,
        summary=summary,
        differential=differential_list or [],
        file_path=None,
    )

    # 5) Guardar marcadores en BD
    if markers_raw:
        crud.add_markers_to_analytic(db=db, analytic_id=analytic.id, markers=markers_raw)

    # 6) Devolver algo útil al frontend
    markers_normalized = _normalize_markers_for_front(markers_raw or [])

    return {
        "id": analytic.id,
        "patient_id": patient_id,
        "patient_alias": alias,
        "file_name": file.filename,
        "summary": summary,
        "differential": "; ".join(differential_list) if differential_list else "",
        "markers": markers_normalized,
        "created_at": analytic.created_at,
    }


# =====================================================
# 3) /analytics/by-patient/{id}  (LISTAR HISTÓRICO)
# =====================================================

@router.get("/by-patient/{patient_id}", response_model=list[AnalyticReturn])
def list_analytics_by_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """Devuelve todas las analíticas ligadas a un paciente concreto."""
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado o no pertenece al usuario.")

    return crud.get_analytics_for_patient(db, patient_id=patient_id)


# =====================================================
# 4) /analytics/chat  (mini‑chat clínico)
# =====================================================

@router.post("/chat")
async def analytics_chat(
    payload: ChatRequest,
):
    """Mini chat clínico orientativo sobre una analítica ya analizada."""
    if not payload.question or not payload.question.strip():
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía.")

    alias = payload.patient_alias or "el paciente"
    base_summary = payload.summary or "una analítica previamente analizada en Galenos.pro."

    diff_txt = payload.differential or ""
    markers_txt = ""
    if payload.markers:
        try:
            names = [m.get("name") for m in payload.markers if m.get("name")]
            if names:
                markers_txt = " Marcadores relevantes: " + ", ".join(names) + "."
        except Exception:
            markers_txt = ""

    system_text = (
        "Eres un asistente clínico que ayuda a un médico a interpretar, de forma prudente, "
        "una analítica ya analizada por Galenos.pro. No puedes ver el PDF original ahora; "
        "solo conoces el resumen, el diagnóstico diferencial y los marcadores extraídos. "
        "NO debes diagnosticar ni prescribir. Tu función es ayudar a ordenar ideas, sugerir "
        "hipótesis generales y recordar que la decisión final corresponde siempre al médico responsable."
    )

    user_text = (
        f"Paciente: {alias}. Resumen previo de la analítica: {base_summary}. "
        f"Diagnóstico diferencial orientativo: {diff_txt}. {markers_txt} "
        f"Pregunta del médico: {payload.question}"
    )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY no está configurada en el backend.",
        )

    text_model = os.getenv("GALENOS_TEXT_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)

    try:
        resp = client.responses.create(
            model=text_model,
            input=[
                {
                    "role": "system",
                    "content": [
                        {"type": "input_text", "text": system_text}
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_text}
                    ],
                },
            ],
        )
        answer = resp.output[0].content[0].text
    except Exception as e:
        print("[Analytics-Chat] Error al llamar a OpenAI:", repr(e))
        raise HTTPException(
            status_code=500,
            detail="No se ha podido generar la respuesta de apoyo clínico para la analítica.",
        )

    disclaimer = (
        "Galenos.pro no diagnostica ni prescribe. Esta respuesta es un apoyo orientativo para el médico. "
        "La interpretación final de la analítica corresponde siempre al médico responsable."
    )

    return JSONResponse(
        {
            "answer": answer,
            "disclaimer": disclaimer,
        }
    )
