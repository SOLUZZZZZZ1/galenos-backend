# utils_vision.py — Lectura de analíticas con GPT-4o Vision (Optimizado Galenos.pro)
#
# - Usa el prompt clínico SYSTEM_PROMPT_GALENOS (tono, prudencia, etc.)
# - Añade un bloque estructural que OBLIGA a devolver JSON con summary/differential/markers
# - Devuelve:
#     summary: str
#     differential_list: list[str]
#     markers_raw: list[dict{name, value, unit, ref_min, ref_max}]
#
# El resto del backend (analytics.py, crud, schemas) puede quedarse tal cual.

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
) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    """
    Envía 1+ imágenes base64 de una analítica a GPT-4o Vision y devuelve:

      - summary: texto clínico orientativo en español
      - differential_list: lista de diagnósticos diferenciales ORIENTATIVOS (strings)
      - markers_raw: lista de marcadores con estructura:
            {
              "name": str,
              "value": float | int | str | None,
              "unit": str | None,
              "ref_min": float | int | None,
              "ref_max": float | int | None
            }

    El modelo está forzado a responder SIEMPRE con JSON.
    """

    if not images_b64:
        return "", [], []

    # 🔥 Bloque estructural: obliga a JSON con summary/differential/markers
    structural_instructions = (
        "Devuelve SIEMPRE un JSON válido con este formato EXACTO:\n"
        "{\n"
        '  \"summary\": \"texto breve en español\",\n'
        '  \"differential\": [\"diagnóstico o causa 1\", \"diagnóstico o causa 2\"],\n'
        '  \"markers\": [\n'
        "    {\n"
        '      \"name\": \"Nombre del marcador (ej. Creatinina)\",\n'
        '      \"value\": número o null,\n'
        '      \"unit\": \"unidad (ej. mg/dL)\" o null,\n'
        '      \"ref_min\": número o null,\n'
        '      \"ref_max\": número o null\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "OBLIGATORIO:\n"
        "- Extrae TODOS los marcadores que aparezcan en la analítica: hemograma, bioquímica, orina, hormonas, etc.\n"
        "- Cuando veas un rango tipo \"(10 - 50)\" o \"4.0 - 6.0\", usa esos valores como ref_min y ref_max.\n"
        "- Si no aparece rango de referencia, deja ref_min y ref_max en null.\n"
        "- NO añadas texto fuera del JSON. NO expliques nada fuera de summary/differential/markers.\n"
    )

    # ⚙️ Combinamos tu prompt clínico (SYSTEM_PROMPT_GALENOS) con las reglas estructurales
    # system_prompt viene desde prompts_galenos.SYSTEM_PROMPT_GALENOS
    combined_system_prompt = (system_prompt or "").strip() + "\n\n" + structural_instructions

    # Contenido multimodal: texto + varias páginas
    user_content: List[Dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Analiza la analítica de laboratorio de {patient_alias}. "
                "Lee todas las páginas y extrae los datos numéricos y rangos."
            ),
        }
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
                        {"type": "text", "text": combined_system_prompt},
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

    # Extraer contenido devuelto (ya debería ser un JSON plano por response_format)
    try:
        msg_content = response.choices[0].message.content
        if isinstance(msg_content, list) and msg_content:
            raw = msg_content[0].text
        else:
            raw = str(msg_content)
    except Exception as e:
        print("[Vision-Analytics] Error extrayendo texto de respuesta:", repr(e))
        return "", [], []

    try:
        data = json.loads(raw)
    except Exception as e:
        print("[Vision-Analytics] Error parseando JSON devuelto por IA:", repr(e))
        print("Contenido crudo devuelto por el modelo:", raw)
        return "", [], []

    # Normalización de campos
    summary = str(data.get("summary", "") or "").strip()
    differential_list = _ensure_list_of_str(data.get("differential", []))
    markers = data.get("markers", []) or []

    normalized_markers: List[Dict[str, Any]] = []
    for m in markers:
        if not isinstance(m, dict):
            continue

        normalized_markers.append(
            {
                "name": m.get("name"),
                "value": m.get("value"),
                "unit": m.get("unit"),
                "ref_min": m.get("ref_min"),
                "ref_max": m.get("ref_max"),
            }
        )

    return summary, differential_list, normalized_markers
