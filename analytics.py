# analytics.py — Analíticas · IA (MVP + mini chat) para Galenos.pro
import os
from typing import List, Optional, Any, Dict

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/analytics", tags=["Analytics"])


class ChatRequest(BaseModel):
    patient_alias: str
    file_name: Optional[str] = None
    markers: Optional[List[Dict[str, Any]]] = None
    summary: Optional[str] = None
    differential: Optional[str] = None
    question: str


@router.post("/analyze")
async def analyze_lab_with_ai(
    alias: str = Form(..., description="Alias del paciente"),
    file: UploadFile = File(..., description="Analítica en PDF o imagen"),
):
    """
    Recibe una analítica (PDF/imagen) y devuelve un resultado de IA simulado.
    No se hace diagnóstico real; solo se generan textos orientativos fijos.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Fichero no válido")


    try:
        # Leemos el fichero para simular procesamiento (no se usa el contenido)
        _ = await file.read()
    except Exception:
        raise HTTPException(status_code=500, detail="No se pudo leer el fichero subido")


    markers: List[dict] = [
        {"name": "Hemoglobina", "value": "13.8 g/dL", "range": "12.0–16.0", "status": "normal"},
        {"name": "Leucocitos", "value": "9.8 x10^9/L", "range": "4.0–11.0", "status": "normal"},
        {"name": "PCR", "value": "12 mg/L", "range": "0–5", "status": "elevado"},
        {"name": "Creatinina", "value": "1.1 mg/dL", "range": "0.7–1.2", "status": "normal"},
    ]

    summary = (
        f"Resumen orientativo para {alias}: se observan parámetros generales dentro de rango, "
        "con una proteína C reactiva (PCR) discretamente elevada que podría sugerir un proceso "
        "inflamatorio leve o en resolución. No se aprecian alteraciones graves en este MVP."
    )

    differential = (
        "Diagnóstico diferencial orientativo (no vinculante): infección leve de vías respiratorias, "
        "proceso inflamatorio inespecífico, reagudización de patología crónica leve. Este texto es "
        "puramente informativo para apoyar la reflexión clínica."
    )

    disclaimer = (
        "Galenos.pro no diagnostica ni prescribe. Esta salida es un apoyo orientativo para el médico. "
        "La decisión clínica final corresponde siempre al facultativo responsable."
    )

    return JSONResponse(
        {
            "patient_alias": alias,
            "file_name": file.filename,
            "markers": markers,
            "summary": summary,
            "differential": differential,
            "disclaimer": disclaimer,
        }
    )


@router.post("/chat")
async def analytics_chat(request: ChatRequest):
    """
    Mini chat clínico orientativo sobre la analítica ya analizada.
    No hace diagnóstico real; reusa el contexto y genera una respuesta de ejemplo.
    """
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía")


    alias = request.patient_alias or "el paciente"
    base_summary = request.summary or "una analítica de control con parámetros mayoritariamente dentro de rango."

    answer_parts = []

    answer_parts.append(
        f"De forma orientativa, teniendo en cuenta que para {alias} describimos previamente {base_summary} "
        "y que este MVP solo maneja datos muy generales, la pregunta que planteas se puede valorar de manera prudente."
    )

    # Comentario simple según marcadores demo si se han enviado
    has_high_pcr = False
    if request.markers:
        for m in request.markers:
            name = (m.get("name") or "").lower()
            status = (m.get("status") or "").lower()
            if "pcr" in name and status not in ("normal", ""):
                has_high_pcr = True
                break

    if has_high_pcr:
        answer_parts.append(
            "El dato de PCR discretamente elevada encaja con contextos inflamatorios leves o en resolución, "
            "pero no permite por sí solo distinguir con precisión la causa concreta."
        )
    else:
        answer_parts.append(
            "Los marcadores incluidos en este MVP no muestran alteraciones graves explícitas. Esto puede ser compatible "
            "con procesos leves o con evolución favorable, pero siempre debe interpretarse en conjunto con la clínica."
        )

    answer_parts.append(
        "En cualquier caso, esta respuesta no sustituye a la evaluación clínica presencial, exploración física, "
        "historia detallada ni a la integración de pruebas complementarias adicionales (imagen, microbiología, etc.)."
    )

    answer_parts.append(
        "Te recomendamos usar este comentario solo como apoyo para ordenar ideas, no como criterio único de decisión. "
        "Si hay duda razonable, es preferible ampliar estudio o reevaluar al paciente según tu criterio profesional."
    )

    disclaimer = (
        "Galenos.pro no diagnostica ni prescribe. Esta conversación es solo un apoyo orientativo para el médico. "
        "La decisión clínica final corresponde siempre al facultativo responsable."
    )

    return JSONResponse(
        {
            "answer": " " .join(answer_parts),
            "disclaimer": disclaimer,
        }
    )
