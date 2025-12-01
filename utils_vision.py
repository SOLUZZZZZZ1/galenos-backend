# utils_vision.py — Lectura de analíticas con GPT-4o Vision usando chat.completions

import json
from typing import List, Tuple, Dict, Any

from openai import OpenAI


def _ensure_list_of_str(value: Any) -> List[str]:
    """Normaliza un campo que debería ser lista de strings."""
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

    Usa la API chat.completions (compatible con openai==1.37.2).

    Devuelve:
      - summary (texto clínico orientativo)
      - differential (lista de posibles causas a valorar)
      - markers (lista de marcadores reales normalizados)
    """

    if not images_b64:
        return "", [], []

    # Construimos contenido multimodal: texto + 1..n imágenes
    user_content: List[Dict[str, Any]] = [
        {
            "type": "text",
            "text": f"Analiza detalladamente la analítica del paciente: {patient_alias}.",
        },
    ]

    for b64 in images_b64:
        user_content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                },
            }
        )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": [
                        {"type": "text", "text": system_prompt},
                    ],
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
            response_format={"type": "json_object"},
        )
    except Exception as e:
        print("[Vision-Analytics] Error al llamar a OpenAI:", repr(e))
        return "", [], []

    try:
        # El contenido viene como lista de bloques; tomamos el primero
        msg_content = response.choices[0].message.content
        if isinstance(msg_content, list) and msg_content:
            raw = msg_content[0].text
        else:
            # fallback por si viene como string plano
            raw = str(msg_content)
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

    normalized_markers: List[Dict[str, Any]] = []
    for m in markers:
        if isinstance(m, dict):
            normalized_markers.append(m)
        else:
            normalized_markers.append({"name": str(m)})

    return summary, differential_list, normalized_markers
