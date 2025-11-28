# utils_vision.py — Lectura real de analíticas con GPT-4o Vision

import json
from typing import List, Tuple
from openai import OpenAI


def analyze_with_ai_vision(
    client: OpenAI,
    images_b64: List[str],
    patient_alias: str,
    model: str,
    system_prompt: str = ""
) -> Tuple[str, List[str], List[dict]]:
    """
    Envía 1+ imágenes base64 de una analítica a GPT-4o Vision.
    Devuelve:
      - summary (texto clínico orientativo)
      - differential (lista de posibles causas a valorar)
      - markers (lista de marcadores reales)
    """

    # Construimos los inputs para Vision
    vision_content = []
    for b64 in images_b64:
        vision_content.append({
            "type": "input_image",
            "image_url": f"data:image/png;base64,{b64}"
        })

    # Llamada a OpenAI
    response = client.responses.create(
        model=model,   # normalmente gpt-4o
        input=[
            {
                "role": "system",
                "content": [
                    {"type": "input_text", "text": system_prompt}
                ]
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": f"Analiza la analítica del paciente: {patient_alias}"},
                    *vision_content
                ]
            }
        ],
        response_format={"type": "json_object"},
    )

    # Extraer JSON
    raw = response.output[0].content[0].text
    data = json.loads(raw)

    summary = data.get("summary", "")
    differential = data.get("differential", [])
    markers = data.get("markers", [])

    return summary, differential, markers
