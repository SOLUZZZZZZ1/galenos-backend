
# analytics.py — Analíticas · IA real (Vision) para Galenos.pro
import os
from typing import List, Optional, Any, Dict

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from openai import OpenAI

from utils_pdf import convert_pdf_to_images
from utils_vision import analyze_with_ai_vision
from prompts_galenos import SYSTEM_PROMPT_GALENOS

router = APIRouter(prefix="/analytics", tags=["Analytics"])


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
    """Construye campos 'range' y 'status' para compatibilidad con el frontend actual.

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


@router.post("/analyze")
async def analyze_lab_with_ai(
    alias: str = Form(..., description="Alias del paciente"),
    file: UploadFile = File(..., description="Analítica en PDF o imagen"),
):
    """Analiza una analítica (PDF/imagen) con IA (Vision) y devuelve un resultado clínico orientativo.

    - Soporta PDF multipágina (convierte cada página en PNG).
    - Soporta imágenes (JPG/PNG, etc.).
    - Usa GPT-4o Vision con un prompt clínico seguro.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Fichero no válido")

    try:
        content = await file.read()
    except Exception:
        raise HTTPException(status_code=500, detail="No se pudo leer el fichero subido")

    if not content:
        raise HTTPException(status_code=400, detail="El fichero está vacío")

    # Determinar tipo por content_type o extensión
    ct = (file.content_type or "").lower()
    name_lower = file.filename.lower()

    images_b64: List[str] = []

    try:
        if "pdf" in ct or name_lower.endswith(".pdf"):
            images_b64 = convert_pdf_to_images(content)
        elif any(ext for ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff"] if name_lower.endswith(ext)):
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
        raise HTTPException(status_code=500, detail="Error interno procesando la analítica.")

    # Configuración OpenAI
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

    # Normalizamos markers al formato que ya usaba el frontend (name/value/range/status)
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
            # Si viene tipo "13.8 g/dL", intentamos sacar el número
            try:
                import re
                match = re.search(r"[-+]?[0-9]*\.?[0-9]+", str(raw_value))
                if match:
                    value_f = float(match.group())
            except Exception:
                value_f = None

        unit = m.get("unit", None)
        if unit is not None:
            unit = str(unit).strip() or None

        ref_min = m.get("ref_min", None)
        ref_max = m.get("ref_max", None)
        try:
            if ref_min is not None:
                ref_min = float(ref_min)
            if ref_max is not None:
                ref_max = float(ref_max)
        except Exception:
            ref_min = None
            ref_max = None

        extras = _build_status_and_range(value_f, ref_min, ref_max, unit)

        markers.append(
            {
                "name": name,
                "value": value_f if value_f is not None else (raw_value if raw_value is not None else None),
                "range": extras["range"],
                "status": extras["status"],
            }
        )

    # Montamos textos
    if differential_list:
        differential_text = "; ".join(differential_list)
    else:
        differential_text = ""

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
            "differential": differential_text,
            "disclaimer": disclaimer,
        }
    )


@router.post("/chat")
async def analytics_chat(request: ChatRequest):
    """Mini chat clínico orientativo sobre la analítica ya analizada.

    Mantiene el espíritu del MVP, pero con textos algo más cuidados.
    No hace diagnóstico real; reusa el contexto y genera una respuesta de ejemplo.
    """
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía")

    alias = request.patient_alias or "el paciente"
    base_summary = request.summary or "una analítica de control con parámetros mayoritariamente dentro de rango."

    answer_parts: List[str] = []

    answer_parts.append(
        f"De forma orientativa, teniendo en cuenta que para {alias} describimos previamente {base_summary}, "
        "podemos responder a tu pregunta con prudencia clínica."
    )

    has_high_inflammatory = False
    if request.markers:
        for m in request.markers:
            name = (m.get("name") or "").lower()
            status = (m.get("status") or "").lower()
            if any(key in name for key in ["pcr", "proteína c reactiva", "vsg", "velocidad de sedimentación"]) and status not in ("normal", ""):
                has_high_inflammatory = True
                break

    if has_high_inflammatory:
        answer_parts.append(
            "Los marcadores inflamatorios discretamente elevados encajan con contextos infecciosos o inflamatorios, "
            "aunque por sí solos no permiten distinguir con precisión la causa concreta."
        )
    else:
        answer_parts.append(
            "Los marcadores disponibles en esta analítica no muestran alteraciones inflamatorias graves. Esto puede ser "
            "compatible con procesos leves o con una evolución favorable, pero siempre debe valorarse junto a la clínica."
        )

    answer_parts.append(
        "En cualquier caso, esta respuesta no sustituye a la evaluación clínica presencial, la exploración física ni la "
        "integración de otras pruebas complementarias (imagen, microbiología, etc.)."
    )

    answer_parts.append(
        "Utiliza este comentario como apoyo para ordenar tus ideas y documentar en la historia, no como criterio único de decisión. "
        "Si persisten dudas razonables, es preferible ampliar estudio o reevaluar al paciente según tu criterio profesional."
    )

    disclaimer = (
        "Galenos.pro no diagnostica ni prescribe. Esta conversación es solo un apoyo orientativo para el médico. "
        "La decisión clínica final corresponde siempre al facultativo responsable."
    )

    return JSONResponse(
        {
            "answer": " ".join(answer_parts),
            "disclaimer": disclaimer,
        }
    )
