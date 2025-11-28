# utils_imagen.py — IA Vision para imágenes médicas (TAC / RM / RX / ECO)

import json
from typing import List, Tuple
from openai import OpenAI


def analyze_medical_image(
    client: OpenAI,
    image_b64: str,
    model: str,
    system_prompt: str
) -> Tuple[str, List[str], List[str]]:
    """
    Envía una imagen médica a GPT-4o Vision.
    Devuelve:
      - summary: descripción orientativa prudente
      - differential: posibles causas a valorar (NO diagnóstico)
      - patterns: lista de patrones visuales detectados
    """

    vision_input = [{
        "type": "input_image",
        "image_url": f"data:image/png;base64,{image_b64}"
    }]

    response = client.responses.create(
        model=model,   # gpt-4o
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
                    {"type": "input_text", "text": "Analiza la siguiente imagen médica:"},
                    *vision_input
                ]
            }
        ],
        response_format={"type": "json_object"},
    )

    raw = response.output[0].content[0].text
    data = json.loads(raw)

    summary = data.get("summary", "")
    differential = data.get("differential", [])
    patterns = data.get("patterns", [])

    return summary, differential, patterns
