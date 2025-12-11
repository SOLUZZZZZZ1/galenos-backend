# utils_vision.py — Lectura de analíticas con GPT-4o Vision (Optimizado Galenos.pro)
#
# Nueva versión:
# - Añade detección automática de la FECHA REAL del análisis ("exam_date")
# - Devuelve 4 valores: summary, differential_list, markers_raw, exam_date_ai
# - exam_date_ai es: "YYYY-MM-DD" o None
#
# Galenos analizará así:
#   1) Si el médico pone fecha manual → se usa esa.
#   2) Si no pone nada → se usa exam_date_ai detectada por IA.
#   3) Si IA no ve fecha → se usa created_at como fallback.
#
# Basado en archivo original :contentReference[oaicite:1]{index=1}

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
    system_prompt: str = "",
) -> Tuple[str, List[str], List[Dict[str, Any]], str | None]:
    """
    Envía 1+ imágenes base64 de una analítica a GPT-4o Vision.
    Devuelve:
      - summary (str)
      - differential_list (list[str])
      - markers_raw (list[dict])
      - exam_date_ai (str "YYYY-MM-DD" o None)
    """

    if not images_b64:
        return "", [], [], None

    # 🔥 BLOQUE ESTRUCTURAL CON FECHA REAL DE ANALÍTICA
    structural_instructions = (
        "Devuelve SIEMPRE un JSON válido EXACTO:\n"
        "{\n"
        '  \"summary\": \"texto breve en español\",\n'
        '  \"differential\": [\"posible causa 1\", \"posible causa 2\"],\n'
        '  \"markers\": [\n'
        "    {\n"
        '      \"name\": \"Nombre del marcador\",\n'
        '      \"value\": número o null,\n'
        '      \"unit\": \"unidad\" o null,\n'
        '      \"ref_min\": número o null,\n'
        '      \"ref_max\": número o null\n'
        "    }\n"
        "  ],\n"
        '  \"exam_date\": \"YYYY-MM-DD\" o null\n'
        "}\n\n"
        "INSTRUCCIONES PARA LA FECHA:\n"
        "- Busca la fecha REAL del análisis o emisión del informe.\n"
        "- Acepta formatos: DD/MM/YY, DD/MM/YYYY, YYYY-MM-DD, \"12 Mayo 2025\", etc.\n"
        "- Transfórmala SIEMPRE a formato YYYY-MM-DD.\n"
        "- Si hay varias fechas, usa la que indique EXTRACCIÓN o INFORME.\n"
        "- Si NO estás seguro, escribe null.\n"
    )

    combined_system_prompt = (system_prompt or "").strip() + "\n\n" + structural_instructions

    # Contenido multimodal
    user_content: List[Dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Analiza la analítica de {patient_alias}. "
                "Extrae TODOS los marcadores y la FECHA REAL de la analítica."
            ),
        }
    ]

    for b64 in images_b64:
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            }
        )

    # Llamada al modelo
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": [{"type": "text", "text": combined_system_prompt}],
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
        return "", [], [], None

    # Extraer contenido
    try:
        msg_content = response.choices[0].message.content
        raw = msg_content[0].text if isinstance(msg_content, list) else str(msg_content)
    except Exception as e:
        print("[Vision-Analytics] Error extrayendo texto de respuesta:", repr(e))
        return "", [], [], None

    # Parsear JSON
    try:
        data = json.loads(raw)
    except Exception as e:
        print("[Vision-Analytics] Error parseando JSON:", repr(e))
        print("Contenido devuelto por IA:", raw)
        return "", [], [], None

    # --- Normalizar campos ---
    summary = (data.get("summary") or "").strip()
    differential_list = _ensure_list_of_str(data.get("differential", []))
    markers = data.get("markers", []) or []

    normalized_markers: List[Dict[str, Any]] = []
    for m in markers:
        if isinstance(m, dict):
            normalized_markers.append(
                {
                    "name": m.get("name"),
                    "value": m.get("value"),
                    "unit": m.get("unit"),
                    "ref_min": m.get("ref_min"),
                    "ref_max": m.get("ref_max"),
                }
            )

    # --- Fecha detectada por IA ---
    exam_date_ai = data.get("exam_date")  # Puede ser "2025-05-13" o None

    return summary, differential_list, normalized_markers, exam_date_ai
