
# utils_vision.py — Lectura real de analíticas con GPT-4o Vision (Optimizado)

import json
from typing import List, Tuple, Dict, Any

from openai import OpenAI


def _ensure_list_of_str(value: Any) -> List[str]:
    """Normaliza un campo que debería ser lista de strings.

    Acepta:
      - list[str]
      - list[dict] (usa str(item))
      - str (lo parte por punto y coma / salto de línea)
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace("\n", ";").split(";") if p.strip()]
        return parts
    return [str(value).strip()]


def analyze_with_ai_vision(
    client: OpenAI,
    images_b64: List[str],
    patient_alias: str,
    model: str,
    system_prompt: str = ""
) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    """Envía 1+ imágenes base64 de una analítica a GPT-4o Vision.

    Devuelve:
      - summary (texto clínico orientativo)
      - differential (lista de posibles causas a valorar, como lista de strings)
      - markers (lista de marcadores reales normalizados)
    """

    if not images_b64:
        return "", [], []

    vision_content = []
    for b64 in images_b64:
        vision_content.append({
            "type": "input_image",
            "image_url": f"data:image/png;base64,{b64}",
        })

    try:
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": [
                        {"type": "input_text", "text": system_prompt}
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"Analiza detalladamente la analítica del paciente: {patient_alias}."
                        },
                        *vision_content,
                    ],
                },
            ],
            response_format={"type": "json_object"},
        )
    except Exception as e:
        print("[Vision-Analytics] Error al llamar a OpenAI:", repr(e))
        return "", [], []

    try:
        raw = response.output[0].content[0].text
    except Exception as e:
        print("[Vision-Analytics] Error extrayendo texto de respuesta:", repr(e))
        return "", [], []

    try:
        data = json.loads(raw)
    except Exception as e:
        print("[Vision-Analytics] Error parseando JSON devuelto por IA:", repr(e))
        return "", [], []

    summary = str(data.get("summary", "") or "").strip()
    differential_list = _ensure_list_of_str(data.get("differential", []))
    markers = data.get("markers", []) or []

    # Nos aseguramos de que markers sea una lista de dicts
    normalized_markers: List[Dict[str, Any]] = []
    for m in markers:
        if isinstance(m, dict):
            normalized_markers.append(m)
        else:
            normalized_markers.append({"name": str(m)})

    return summary, differential_list, normalized_markers
