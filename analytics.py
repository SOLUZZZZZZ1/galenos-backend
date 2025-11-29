# analytics.py — Analíticas · IA (MVP) para Galenos.pro
import os
from typing import List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/analytics", tags=["Analytics"])

# En un futuro se podría integrar aquí un modelo de IA real (OpenAI, etc.).
# De momento, este MVP genera un resumen orientativo a partir de datos fijos
# y del alias del paciente + nombre del fichero.


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

    # En un futuro podríamos guardar el fichero, extraer texto, etc.
    # De momento, lo leemos por completo para 'simular' procesamiento y lo ignoramos.
    try:
        _ = await file.read()
    except Exception:
        raise HTTPException(status_code=500, detail="No se pudo leer el fichero subido")

    # Marcadores de ejemplo (MVP)
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
