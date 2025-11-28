"""
app.py — Backend Galenos.pro con IA integrada (modo seguro · analíticas)

Este backend está pensado para:

- Recibir una analítica (PDF/imagen) en /uploads
- De momento: usar marcadores DEMO (Glucosa, Creatinina, HbA1c...)
- Pedir a OpenAI que genere:
  · summary      → resumen clínico orientativo
  · differential → lista de posibles causas / diagnósticos diferenciales a valorar

SIEMPRE:
- Sin diagnosticar ni prescribir.
- Recalcando que la decisión final corresponde al médico responsable.
"""

import os
import json
from typing import List, Optional, Tuple

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from openai import OpenAI


# ======================================================
#  CONFIGURACIÓN Y CLIENTE OPENAI
# ======================================================

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    # El backend puede arrancar sin ella, pero /uploads fallará si no hay clave.
    print("[Galenos] AVISO: OPENAI_API_KEY no definida en entorno.")

client = OpenAI()  # Usará OPENAI_API_KEY del entorno

MODEL_GENERAL = os.environ.get("OPENAI_MODEL_GENERAL", "gpt-4o-mini")


# ======================================================
#  MODELOS DE DATOS
# ======================================================

class Marker(BaseModel):
    name: str = Field(..., description="Nombre del marcador, p.ej. Glucosa")
    value: float = Field(..., description="Valor numérico del marcador")
    unit: str = Field(..., description="Unidad, p.ej. mg/dL")
    ref_min: Optional[float] = Field(None, description="Límite inferior de referencia")
    ref_max: Optional[float] = Field(None, description="Límite superior de referencia")


class Extraction(BaseModel):
    patient_alias: str
    summary: str
    differential: List[str] = Field(
        default_factory=list,
        description="Lista de posibles causas / diagnósticos diferenciales a valorar"
    )
    markers: List[Marker]


class PingOut(BaseModel):
    ok: bool
    message: str
    version: str


# ======================================================
#  APLICACIÓN FASTAPI + CORS
# ======================================================

app = FastAPI(
    title="Galenos.pro API",
    description="Backend Galenos.pro con módulo de analíticas asistido por IA.",
    version="0.3.0",
)

# CORS: leer de variable CORS_ORIGINS o permitir todo en desarrollo
cors_origins_raw = os.environ.get("CORS_ORIGINS", "*")
if cors_origins_raw == "*" or not cors_origins_raw.strip():
    allow_origins = ["*"]
else:
    allow_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ======================================================
#  HELPERS IA
# ======================================================

def build_markers_demo() -> List[Marker]:
    """
    De momento usamos marcadores DEMO. Más adelante:
    - Leeremos la analítica real (PDF/imagen)
    - Extraeremos datos con IA de visión o OCR
    """
    return [
        Marker(
            name="Glucosa",
            value=105,
            unit="mg/dL",
            ref_min=70,
            ref_max=110,
        ),
        Marker(
            name="Creatinina",
            value=1.1,
            unit="mg/dL",
            ref_min=0.7,
            ref_max=1.3,
        ),
        Marker(
            name="HbA1c",
            value=6.2,
            unit="%",
            ref_min=4.0,
            ref_max=5.6,
        ),
    ]


def markers_to_prompt(markers: List[Marker], patient_alias: str) -> str:
    """
    Construye un texto estructurado para pasar a la IA a partir de los marcadores.
    """
    lines = []
    lines.append(f"Paciente (alias): {patient_alias}")
    lines.append("Resultados analíticos (marcadores clave):")
    for m in markers:
        ref = ""
        if m.ref_min is not None and m.ref_max is not None:
            ref = f" (rango ref. {m.ref_min}–{m.ref_max} {m.unit})"
        lines.append(f"- {m.name}: {m.value} {m.unit}{ref}")
    return "
".join(lines)


def call_openai_for_summary_and_differential(
    prompt_text: str,
) -> Tuple[str, List[str]]:
    """
    Llama a OpenAI para obtener summary + differential en JSON.
    Modo totalmente prudente: no diagnostica ni prescribe.
    """
    if not OPENAI_API_KEY:
        # Sin clave devolvemos un fallback muy suave
        fallback_summary = (
            "Resumen orientativo no generado por IA (falta OPENAI_API_KEY). "
            "Los valores analíticos deben ser interpretados por el médico "
            "responsable en el contexto clínico completo."
        )
        return fallback_summary, []

    system_prompt = (
        "Eres un asistente médico clínico que ayuda a médicos a interpretar "
        "analíticas de laboratorio y su evolución. Tu función es ORIENTATIVA.

"
        "REGLAS IMPORTANTES:
"
        "- NUNCA des un diagnóstico definitivo.
"
        "- NUNCA prescribas tratamientos ni ajustes de medicación.
"
        "- Habla siempre de 'posibles causas', 'diagnósticos diferenciales a valorar', "
        "y 'correlación clínica necesaria'.
"
        "- Recuerda que la decisión final corresponde siempre al médico responsable.

"
        "FORMATO DE RESPUESTA:
"
        "Devuelve SIEMPRE un JSON con esta forma exacta:
"
        "{
"
        '  "summary": "texto breve en español", 
'
        '  "differential": ["posible causa 1", "posible causa 2", ...]
"
        "}
"
        "Nada más, sin texto adicional fuera del JSON."
    )

    user_prompt = (
        "A partir de los siguientes datos de analítica de un paciente, genera:
"
        "- Un resumen clínico orientativo (summary).
"
        "- Una lista de posibles diagnósticos diferenciales o causas a valorar (differential).

"
        "Datos del paciente y analítica:

"
        f"{prompt_text}
"
    )

    try:
        response = client.responses.create(
            model=MODEL_GENERAL,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_prompt}],
                },
            ],
            response_format={"type": "json_object"},
        )

        # Extraemos el primer output de texto
        content = response.output[0].content[0].text
        data = json.loads(content)

        summary = str(data.get("summary", "")).strip()
        differential_raw = data.get("differential", []) or []
        differential = [str(item).strip() for item in differential_raw if str(item).strip()]

        if not summary:
            summary = (
                "La IA no ha devuelto un resumen claro. Interpretar la analítica "
                "siempre bajo el criterio del médico responsable."
            )

        return summary, differential

    except Exception as e:
        # Ante cualquier error, devolvemos algo prudente y no rompemos el flujo.
        print(f"[Galenos] Error llamando a OpenAI: {e!r}")
        fallback_summary = (
            "No se ha podido generar el resumen con IA en este momento. "
            "Los valores deben interpretarse por el médico responsable. "
            "Inténtalo de nuevo más tarde."
        )
        return fallback_summary, []


# ======================================================
#  ENDPOINTS
# ======================================================

@app.get("/ping", response_model=PingOut)
def ping():
    """
    Verifica que el backend de Galenos.pro está vivo.
    """
    return PingOut(ok=True, message="Galenos.pro backend con IA vivo", version="0.3.0")


@app.post("/uploads")
async def upload_analytic(
    file: UploadFile = File(...),
    patient_alias: str = Form(...),
):
    """
    Endpoint MVP de subida de analítica.

    Versión actual:
    - Acepta un archivo (PDF/imagen) pero todavía no lo analiza.
    - Genera marcadores DEMO.
    - Llama a OpenAI con esos marcadores para obtener summary + differential.
    - Devuelve estructura completa para que el frontend ya pueda mostrar:
        · Tabla de marcadores
        · Resumen clínico orientativo
        · Lista de posibles causas a valorar
    """

    if not file.filename:
        raise HTTPException(status_code=400, detail="No se ha enviado ningún archivo")

    # En futuras versiones podríamos leer el contenido:
    # content_bytes = await file.read()
    # y usarlo con visión/IA. De momento, no es necesario para el MVP.

    markers = build_markers_demo()
    prompt_text = markers_to_prompt(markers, patient_alias)
    summary, differential = call_openai_for_summary_and_differential(prompt_text)

    extraction = Extraction(
        patient_alias=patient_alias,
        summary=summary,
        differential=differential,
        markers=markers,
    )

    return {"ok": True, "extraction": extraction}
