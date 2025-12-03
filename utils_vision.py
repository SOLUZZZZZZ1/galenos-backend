# utils_vision.py — Lectura de analíticas con GPT-4o Vision (CORREGIDO y OBLIGADO A JSON)
# Autocontenido y robusto — Galenos.pro

import json
from typing import List, Tuple, Dict, Any
from openai import OpenAI


def analyze_with_ai_vision(
    client: OpenAI,
    images_b64: List[str],
    patient_alias: str,
    model: str,
    system_prompt: str = ""
) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    """
    Analiza una analítica con Vision y OBLIGA una salida JSON con:
      - summary: str
      - differential: [str]
      - markers: [{ name, value, unit, ref_min, ref_max }]
    """

    if not images_b64:
        return "", [], []

    # 🔥 INSTRUCCIÓN CRÍTICA → obliga al modelo a devolver markers
    system_text = (
        "Eres un extractor clínico. Debes devolver SIEMPRE un JSON válido con este formato exacto:\n"
        "{\n"
        '  "summary": "texto breve en español",\n'
        '  "differential": ["diagnóstico1", "diagnóstico2"],\n'
        '  "markers": [\n'
        "    {\n"
        '      "name": "Creatinina",\n'
        '      "value": 1.80,\n'
        '      "unit": "mg/dL",\n'
        '      "ref_min": 0.70,\n'
        '      "ref_max": 1.30\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "OBLIGACIONES:\n"
        "- Extrae TODOS los marcadores que aparezcan en la analítica (línea a línea).\n"
        "- Extrae SIEMPRE: nombre, valor, unidad, rango mínimo, rango máximo.\n"
        "- Si no hay un rango claro, ref_min/ref_max debe ser null.\n"
        "- NO añadas nada fuera del JSON. NO añadas explicaciones. NO escribas texto libre.\n"
    )

    # Construimos el contenido (1 o varias páginas)
    user_content: List[Dict[str, Any]] = [
        {"type": "text", "text": f"Analiza esta analítica del paciente {patient_alias} y extrae todos los valores."},
    ]

    for b64 in images_b64:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"}
        })

    # 🔥 PEDIMOS JSON ESTRICTO
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": system_text},
                ],
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
        response_format={"type": "json_object"},
    )

    # Extraer contenido
    msg_content = response.choices[0].message.content
    if isinstance(msg_content, list) and msg_content:
        raw = msg_content[0].text
    else:
        raw = str(msg_content)

    try:
        data = json.loads(raw)
    except Exception as e:
        print("[Vision-Analytics] ERROR PARSEANDO JSON:", e, raw)
        return "", [], []

    # Normalización
    summary = str(data.get("summary", "") or "").strip()
    differential_list = data.get("differential", []) or []
    markers = data.get("markers", []) or []

    # Asegurar estructura
    normalized_markers = []
    for m in markers:
        if not isinstance(m, dict):
            continue
        normalized_markers.append({
            "name": m.get("name"),
            "value": m.get("value"),
            "unit": m.get("unit"),
            "ref_min": m.get("ref_min"),
            "ref_max": m.get("ref_max"),
        })

    return summary, differential_list, normalized_markers
