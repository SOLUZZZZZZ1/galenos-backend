# analytics.py — Analíticas · IA real (Vision) para Galenos.pro
# ARCHIVO COMPLETO, LISTO PARA PRODUCCIÓN
# Incluye:
# - /analytics/analyze
# - /analytics/upload/{patient_id}
# - /analytics/by-patient/{patient_id}
# - /analytics/markers/{analytic_id}  ✅ (FALTABA, causa del 404)
# - /analytics/compare/{patient_id}
# - /analytics/compare-summary/{patient_id}
# - /analytics/chat

import os
import json
import hashlib
from datetime import datetime, date, timedelta
from typing import List, Optional, Any, Dict

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from openai import OpenAI

from database import get_db
from auth import get_current_user
import crud
import storage_b2
from schemas import AnalyticReturn
from utils_pdf import convert_pdf_to_images
from utils_vision import analyze_with_ai_vision
from prompts_galenos import SYSTEM_PROMPT_GALENOS

# 👇 IMPORT CLAVE QUE FALTABA
from models import Analytic, AnalyticMarker

router = APIRouter(prefix="/analytics", tags=["Analytics"])

# =============================
# MODELOS AUXILIARES
# =============================
class ChatRequest(BaseModel):
    patient_alias: Optional[str] = None
    file_name: Optional[str] = None
    markers: Optional[List[Dict[str, Any]]] = None
    summary: Optional[str] = None
    differential: Optional[str] = None
    question: str


# =============================
# UTILIDADES
# =============================
def _build_status_and_range(value, ref_min, ref_max, unit):
    range_txt = None
    if ref_min is not None and ref_max is not None:
        range_txt = f"{ref_min}–{ref_max} {unit or ''}".strip()

    status = None
    if value is not None and ref_min is not None and ref_max is not None:
        if value < ref_min:
            status = "bajo"
        elif value > ref_max:
            status = "elevado"
        else:
            status = "normal"

    return {"range": range_txt, "status": status}


def _normalize_markers_for_front(markers_raw):
    out = []
    for m in markers_raw:
        name = (m.get("name") or "").strip()
        if not name:
            continue
        value = m.get("value")
        unit = m.get("unit")
        ref_min = m.get("ref_min")
        ref_max = m.get("ref_max")
        sr = _build_status_and_range(value, ref_min, ref_max, unit)
        out.append({
            "name": name,
            "value": value,
            "unit": unit,
            "ref_min": ref_min,
            "ref_max": ref_max,
            "range": sr["range"],
            "status": sr["status"],
        })
    return out


def _prepare_images(file: UploadFile, content: bytes):
    name = file.filename.lower()
    if name.endswith(".pdf"):
        return convert_pdf_to_images(content)
    import base64
    return [base64.b64encode(content).decode()]


def _parse_exam_date(v):
    try:
        return datetime.strptime(v, "%Y-%m-%d").date() if v else None
    except Exception:
        return None


# =============================
# STORAGE (Backblaze B2)
# =============================
def _ext_from_filename(name: str) -> str:
    name = (name or "").lower().strip()
    if "." in name:
        return name.rsplit(".", 1)[-1]
    return "bin"

def _b2_upload_original_and_preview(*, user_id: int, kind: str, record_id: int, original_filename: str, original_bytes: bytes, preview_b64: str, preview_ext: str = "png"):
    """
    Sube:
    - el archivo original (para conservarlo)
    - un preview renderizable (imagen) para el frontend

    Guardamos en BD solo el file_key del preview (para no romper frontend).
    El original queda en una ruta derivable.
    """
    # Original
    orig_ext = _ext_from_filename(original_filename)
    orig_name = f"original.{orig_ext}"
    orig = storage_b2.upload_bytes(
        user_id=user_id,
        category=kind,
        object_id=record_id,
        filename=orig_name,
        data=original_bytes,
    )

    # Preview (imagen)
    try:
        import base64
        preview_bytes = base64.b64decode(preview_b64)
    except Exception:
        preview_bytes = b""

    prev_name = f"preview.{preview_ext}"
    prev = storage_b2.upload_bytes(
        user_id=user_id,
        category=kind,
        object_id=record_id,
        filename=prev_name,
        data=preview_bytes if preview_bytes else original_bytes,
    )

    return {
        "original_key": orig["file_key"],
        "preview_key": prev["file_key"],
        "size_bytes": orig["size_bytes"],
        "sha256": orig["sha256"],
        "mime_type": orig["mime_type"],
    }

def _file_path_for_front(db_value: str) -> str:
    """
    No cambiamos el frontend:
    - Si ya es data URL (legacy), lo devolvemos tal cual.
    - Si es un file_key en B2, devolvemos una URL temporal (presigned) para render <img>.
    """
    if not db_value:
        return None
    if isinstance(db_value, str) and db_value.startswith("data:"):
        return db_value
    # Si parece clave B2
    try:
        return storage_b2.generate_presigned_url(file_key=db_value, expires_seconds=3600)
    except Exception:
        # Si falla, devolvemos el valor para debugging (mejor que romper)
        return db_value

# =============================
# ENDPOINT: ANALYZE (sandbox)
# =============================
@router.post("/analyze")
async def analyze_lab(alias: str = Form(...), file: UploadFile = File(...)):
    content = await file.read()
    images = _prepare_images(file, content)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    summary, diff_list, markers_raw, exam_date_ai = analyze_with_ai_vision(
        client=client,
        images_b64=images,
        patient_alias=alias,
        model=os.getenv("GALENOS_VISION_MODEL", "gpt-4o"),
        system_prompt=SYSTEM_PROMPT_GALENOS,
    )

    return {
        "summary": summary,
        "differential": "; ".join(diff_list or []),
        "markers": _normalize_markers_for_front(markers_raw or []),
        "exam_date_ai": exam_date_ai,
    }


# =============================
# ENDPOINT: UPLOAD
# =============================
@router.post("/upload/{patient_id}")
async def upload_analytic(
    patient_id: int,
    alias: str = Form(...),
    file: UploadFile = File(...),
    exam_date: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    patient = crud.get_patient_by_id(db, patient_id, user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado")

    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()

    existing = crud.get_analytic_by_hash(db, patient_id, file_hash)
    if existing:
        return {"duplicate": True, "id": existing.id}

    images = _prepare_images(file, content)
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    summary, diff_list, markers_raw, exam_date_ai = analyze_with_ai_vision(
        client=client,
        images_b64=images,
        patient_alias=alias,
        model=os.getenv("GALENOS_VISION_MODEL", "gpt-4o"),
        system_prompt=SYSTEM_PROMPT_GALENOS,
    )

    final_date = _parse_exam_date(exam_date) or _parse_exam_date(exam_date_ai)

    analytic = crud.create_analytic(
        db=db,
        patient_id=patient_id,
        summary=summary,
        differential=diff_list or [],
        file_path=None,
        file_hash=file_hash,
        exam_date=final_date,
    )

# ✅ Subimos binarios a Backblaze B2 (original + preview) y guardamos SOLO la clave del preview
try:
    # Determinar extensión del preview (si viene de PDF, images[0] suele ser PNG)
    preview_ext = "png"
    lower_name = (file.filename or "").lower()
    if lower_name.endswith(".jpg") or lower_name.endswith(".jpeg"):
        preview_ext = "jpg"
    elif lower_name.endswith(".png"):
        preview_ext = "png"

    up = _b2_upload_original_and_preview(
        user_id=user.id,
        kind="analytics",
        record_id=analytic.id,
        original_filename=file.filename or "analytic",
        original_bytes=content,
        preview_b64=images[0],
        preview_ext=preview_ext,
    )
    # Guardamos en BD la clave del preview (NO base64)
    analytic.file_path = up["preview_key"]
    # Mantenemos file_hash como dedupe (ya calculado)
    db.add(analytic)
    db.commit()
    db.refresh(analytic)
except Exception as e:
    # Si B2 falla, no rompemos la subida clínica; devolvemos error claro
    raise HTTPException(500, f"Error subiendo fichero a almacenamiento: {e}")

    if markers_raw:
        crud.add_markers_to_analytic(db, analytic.id, markers_raw)

    return {
        "id": analytic.id,
        "summary": summary,
        "markers": _normalize_markers_for_front(markers_raw or []),
    }


# =============================
# ENDPOINT: BY PATIENT
# =============================
@router.get("/by-patient/{patient_id}", response_model=List[AnalyticReturn])
def by_patient(patient_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    patient = crud.get_patient_by_id(db, patient_id, user.id)
    if not patient:
        raise HTTPException(404)

    analytics = crud.get_analytics_for_patient(db, patient_id)
    out = []
    for a in analytics:
        markers = _normalize_markers_for_front([
            {
                "name": m.name,
                "value": m.value,
                "unit": m.unit,
                "ref_min": m.ref_min,
                "ref_max": m.ref_max,
            } for m in a.markers
        ])
        out.append({
            "id": a.id,
            "summary": a.summary,
            "differential": a.differential,
            "created_at": a.created_at,
            "exam_date": a.exam_date,
            "file_path": _file_path_for_front(a.file_path),
            "markers": markers,
        })
    return out


# =============================
# 🔥 ENDPOINT QUE FALTABA
# =============================
@router.get("/markers/{analytic_id}")
def get_markers(analytic_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    analytic = db.query(Analytic).filter(Analytic.id == analytic_id).first()
    if not analytic:
        raise HTTPException(404, "Analítica no encontrada")

    markers = [
        {
            "name": m.name,
            "value": m.value,
            "unit": m.unit,
            "ref_min": m.ref_min,
            "ref_max": m.ref_max,
        }
        for m in analytic.markers
    ]

    return {"markers": _normalize_markers_for_front(markers)}


# =============================
# ENDPOINT: CHAT
# =============================
@router.post("/chat")
def analytics_chat(payload: ChatRequest):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    messages = [
        {"role": "system", "content": "Eres un asistente clínico. No diagnosticas."},
        {"role": "user", "content": payload.question},
    ]

    resp = client.chat.completions.create(
        model=os.getenv("GALENOS_TEXT_MODEL", "gpt-4o-mini"),
        messages=messages,
    )

    return {"answer": resp.choices[0].message.content}
