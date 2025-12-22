from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime
import os
import urllib.request

from openai import OpenAI

from database import get_db
from auth import get_current_user
from models import Imaging, Patient, User
import storage_b2

from prompts_imagen_cirugia import PROMPT_IMAGEN_CIRUGIA
from utils_imagen_cirugia import analyze_surgical_photo

router = APIRouter(prefix="/imaging/cosmetic", tags=["Imaging-Cosmetic"])

class AnalyzeIn(BaseModel):
    context: str | None = None

def _get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(500, "OPENAI_API_KEY no está configurada.")
    return OpenAI(api_key=api_key)

def _fetch_preview_bytes(file_key: str) -> bytes:
    if not file_key:
        return b""
    try:
        url = storage_b2.generate_presigned_url(file_key=file_key, expires_seconds=600)
        with urllib.request.urlopen(url) as r:
            return r.read()
    except Exception as e:
        print("[Cosmetic] Error descargando preview:", repr(e))
        return b""

@router.post("/{image_id}/analyze")
def analyze_cosmetic_image(
    image_id: int,
    payload: AnalyzeIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    img = (
        db.query(Imaging)
        .join(Patient, Patient.id == Imaging.patient_id)
        .filter(Imaging.id == image_id, Patient.doctor_id == current_user.id)
        .first()
    )
    if not img:
        raise HTTPException(404, "Imagen no encontrada o no autorizada.")

    itype = (img.type or "").upper().strip()
    if not itype.startswith("COSMETIC"):
        raise HTTPException(400, "Esta imagen no está marcada como COSMETIC_* (cirugía).")

    image_bytes = _fetch_preview_bytes(img.file_path)
    if not image_bytes:
        raise HTTPException(500, "No se pudo cargar la imagen desde almacenamiento.")

    client = _get_openai_client()
    model = os.getenv("GALENOS_VISION_MODEL_COSMETIC") or os.getenv("GALENOS_VISION_MODEL") or "gpt-4o"

    text = analyze_surgical_photo(
        client=client,
        image_bytes=image_bytes,
        model=model,
        system_prompt=PROMPT_IMAGEN_CIRUGIA,
        extra_context=(payload.context or "").strip() or None,
    )
    if not text:
        raise HTTPException(500, "La IA no devolvió un análisis válido.")

    img.ai_description_draft = text
    img.ai_description_updated_at = datetime.utcnow()
    db.add(img)
    db.commit()
    db.refresh(img)

    return {
        "id": img.id,
        "type": img.type,
        "ai_description_draft": img.ai_description_draft,
        "ai_description_updated_at": img.ai_description_updated_at,
        "disclaimer": "Análisis descriptivo. No diagnóstico.",
    }
