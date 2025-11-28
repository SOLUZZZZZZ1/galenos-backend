# analytics.py — Endpoints para analíticas reales con IA (con fallback seguro)

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
from auth import get_current_user
from database import get_db

from openai import OpenAI
import base64

from utils_pdf import convert_pdf_to_images
from utils_vision import analyze_with_ai_vision
from prompts_galenos import SYSTEM_PROMPT_GALENOS
import crud
from schemas import AnalyticReturn

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def get_openai_client():
    """
    Crea un cliente OpenAI. Si falla (por problemas de entorno, proxies, etc.),
    devuelve None para que el backend siga vivo y use un fallback.
    """
    try:
        return OpenAI()
    except Exception as e:
        print("[OpenAI] Error creando cliente OpenAI:", repr(e))
        return None


@router.post("/upload", response_model=AnalyticReturn)
async def upload_analytic(
    patient_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    # Verificar paciente
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado.")

    filename = file.filename.lower()
    content = await file.read()

    # Convertir archivo a imágenes base64
    if filename.endswith(".pdf"):
        images_b64 = convert_pdf_to_images(content)
    else:
        images_b64 = [base64.b64encode(content).decode()]

    if not images_b64:
        raise HTTPException(400, "No se pudo procesar la analítica.")

    # Intentar crear cliente OpenAI
    client = get_openai_client()

    if client:
        # IA Vision real
        try:
            summary, differential, markers = analyze_with_ai_vision(
                client=client,
                images_b64=images_b64,
                patient_alias=patient.alias,
                model="gpt-4o",
                system_prompt=SYSTEM_PROMPT_GALENOS,
            )
        except Exception as e:
            print("[OpenAI] Error llamando a Vision:", repr(e))
            # Fallback si la llamada a IA falla
            summary = (
                "No se ha podido generar el resumen con IA en este momento. "
                "Interpretar la analítica bajo el criterio clínico."
            )
            differential = ["Error temporal de IA, repetir más tarde."]
            markers = []
    else:
        # Fallback si no tenemos cliente OpenAI
        summary = (
            "IA no disponible en este entorno. Esta es una respuesta de ejemplo. "
            "Interprete la analítica bajo su criterio clínico."
        )
        differential = ["Posible alteración metabólica a valorar.", "Correlación clínica necesaria."]
        markers = []

    # Guardar en BD
    analytic = crud.create_analytic(
        db=db,
        patient_id=patient.id,
        summary=summary,
        differential=differential,
        file_path=None,
    )

    if markers:
        crud.add_markers_to_analytic(db, analytic.id, markers)

    # Recargar analítica con markers
    analytics_for_patient = crud.get_analytics_for_patient(db, patient.id)
    # La primera será la más reciente
    full = next((a for a in analytics_for_patient if a.id == analytic.id), analytic)

    return full
