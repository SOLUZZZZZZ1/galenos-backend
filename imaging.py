# imaging.py — Endpoints para TAC/RM/RX/ECO reales + mini chat radiológico · Galenos.pro

from typing import Optional, List

import os
import base64

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from openai import OpenAI

from auth import get_current_user
from database import get_db
import crud
from schemas import ImagingReturn
from utils_pdf import convert_pdf_to_images
from utils_imagen import analyze_medical_image
from prompts_imagen import SYSTEM_PROMPT_IMAGEN

router = APIRouter(prefix="/imaging", tags=["Imaging"])


# ===========================================
# Helper: obtener cliente OpenAI
# ===========================================

def _get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY no está configurada en el backend."
        )
    return OpenAI(api_key=api_key)


# ===========================================
# 1) SUBIDA Y ANÁLISIS DE IMAGEN MÉDICA
# ===========================================

@router.post("/upload", response_model=ImagingReturn)
async def upload_imaging(
    patient_id: int = Form(..., description="ID del paciente en Galenos"),
    img_type: str = Form("imagen", description="Tipo de estudio: RX / TAC / RM / ECO / otro"),
    context: Optional[str] = Form(
        None,
        description="Contexto clínico opcional (tos, disnea, dolor, tiempo de evolución, etc.)"
    ),
    file: UploadFile = File(..., description="Imagen médica o PDF con la imagen"),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """Sube una imagen médica (RX, TAC, RM, ECO, etc.) o PDF y la analiza con IA Vision.

    - Verifica que el paciente pertenece al médico actual.
    - Convierte PDF a imágenes si es necesario.
    - Llama a GPT-4o Vision con un prompt clínico prudente.
    - Guarda el resumen, el diferencial y los patrones en la BD.
    """
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado.")

    try:
        content = await file.read()
    except Exception:
        raise HTTPException(status_code=500, detail="No se pudo leer el fichero de imagen.")

    if not content:
        raise HTTPException(status_code=400, detail="El fichero está vacío.")

    ct = (file.content_type or "").lower()
    name_lower = (file.filename or "").lower()

    img_b64: Optional[str] = None

    try:
        if "pdf" in ct or name_lower.endswith(".pdf"):
            # PDF de TAC/RM/RX: convertimos a imágenes y usamos la primera página (representativa)
            images_b64 = convert_pdf_to_images(content, max_pages=10, dpi=200)
            if not images_b64:
                raise HTTPException(
                    status_code=400,
                    detail="No se han podido extraer imágenes legibles del PDF."
                )
            img_b64 = images_b64[0]
        elif any(name_lower.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff"]):
            img_b64 = base64.b64encode(content).decode("utf-8")
        else:
            # Intentamos tratarlo como PDF por si acaso
            images_b64 = convert_pdf_to_images(content, max_pages=5, dpi=200)
            if images_b64:
                img_b64 = images_b64[0]
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Formato de archivo no soportado para imagen médica."
                )
    except HTTPException:
        raise
    except Exception as e:
        print("[Imaging] Error preparando imagen para Vision:", repr(e))
        raise HTTPException(status_code=500, detail="Error interno procesando la imagen.")

    client = _get_openai_client()
    model = os.getenv("GALENOS_VISION_MODEL", "gpt-4o")

    summary, differential_list, patterns = analyze_medical_image(
        client=client,
        image_b64=img_b64,
        model=model,
        system_prompt=SYSTEM_PROMPT_IMAGEN,
        extra_context=context,
    )

    # differential_list es una lista de strings → la unimos en un texto breve
    differential_text = "; ".join(differential_list) if differential_list else ""

    # Normalizamos img_type a algo corto y claro
    normalized_type = (img_type or "imagen").strip().upper()

    # Guardar en BD
    imaging = crud.create_imaging(
        db=db,
        patient_id=patient.id,
        img_type=normalized_type,
        summary=summary,
        differential=differential_text,
        file_path=None,  # futuro: ruta en S3/Cloudflare si se desea
    )

    crud.add_patterns_to_imaging(db, imaging.id, patterns or [])

    return imaging


# ===========================================
# 1 bis) LISTAR IMÁGENES POR PACIENTE
# ===========================================

@router.get("/by-patient/{patient_id}", response_model=list[ImagingReturn])
def list_imaging_by_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """Devuelve todos los estudios de imagen de un paciente concreto."""
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado.")

    return crud.get_imaging_for_patient(db, patient_id)


# ===========================================
# 2) MINI CHAT CLÍNICO SOBRE IMAGEN MÉDICA
# ===========================================

class ImagingChatRequest(BaseModel):
    """Petición para el mini chat radiológico.

    Se puede usar de dos formas:
    - Con summary + patterns directamente (desde frontend).
    - Opcionalmente podría ampliarse para usar imaging_id en el futuro.
    """
    patient_alias: Optional[str] = None
    summary: Optional[str] = None
    patterns: Optional[List[str]] = None
    question: str


@router.post("/chat")
async def imaging_chat(
    payload: ImagingChatRequest,
    current_user = Depends(get_current_user),
):
    """Mini chat orientativo sobre la imagen ya analizada.

    NO añade nueva información diagnóstica, solo ayuda al médico a razonar
    y documentar a partir del resumen y los patrones ya generados.
    """
    if not payload.question or not payload.question.strip():
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía.")

    alias = payload.patient_alias or "el paciente"
    base_summary = payload.summary or "una imagen médica previamente analizada en Galenos.pro."

    patterns_txt = ""
    if payload.patterns:
        bullets = "; ".join([p for p in payload.patterns if p])
        if bullets:
            patterns_txt = f"Patrones descritos previamente: {bullets}."

    system_text = (
        "Eres un asistente clínico que ayuda a un médico a interpretar, de forma prudente, "
        "una imagen médica ya analizada. No puedes ver la imagen ahora; solo conoces el resumen "
        "y los patrones descritos. NO debes diagnosticar ni prescribir. "
        "Tu función es ayudar a ordenar ideas y sugerir líneas de reflexión clínica general, "
        "recordando siempre que la interpretación final corresponde al radiólogo/médico responsable."
    )

    user_text = (
        f"Paciente: {alias}. Resumen previo de la imagen: {base_summary}. "
        f"{patterns_txt} Pregunta del médico: {payload.question}"
    )

    client = _get_openai_client()
    text_model = os.getenv("GALENOS_TEXT_MODEL", "gpt-4o-mini")

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
        print("[Imaging-Chat] Error al llamar a OpenAI:", repr(e))
        raise HTTPException(
            status_code=500,
            detail="No se ha podido generar la respuesta de apoyo radiológico."
        )

    disclaimer = (
        "Galenos.pro no diagnostica ni prescribe. Esta respuesta es un apoyo orientativo para el médico. "
        "La interpretación final de la imagen corresponde siempre al radiólogo/médico responsable."
    )

    return JSONResponse(
        {
            "answer": answer,
            "disclaimer": disclaimer,
        }
    )
