
# utils_imagen.py — IA Vision para imágenes médicas (TAC / RM / RX / ECO) · Optimizado

import json
from typing import List, Tuple, Any

from openai import OpenAI


def _ensure_list_of_str(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace("\n", ";").split(";") if p.strip()]
        return parts
    return [str(value).strip()]


def analyze_medical_image(
    client: OpenAI,
    image_b64: str,
    model: str,
    system_prompt: str,
    extra_context: str | None = None,
) -> Tuple[str, List[str], List[str]]:
    """Envía una imagen médica a GPT-4o Vision.

    Devuelve:
      - summary: descripción orientativa prudente
      - differential: posibles causas generales a valorar (lista de strings)
      - patterns: lista de patrones visuales detectados (lista de strings)
    """

    if not image_b64:
        return "", [], []

    vision_input = [
        {
            "type": "input_image",
            "image_url": f"data:image/png;base64,{image_b64}",
        }
    ]

    user_text = "Analiza la siguiente imagen médica de forma prudente."
    if extra_context:
        user_text += f" Contexto adicional proporcionado por el médico: {extra_context}."

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
                        {"type": "input_text", "text": user_text},
                        *vision_input,
                    ],
                },
            ],
            response_format={"type": "json_object"},
        )
    except Exception as e:
        print("[Vision-Imaging] Error al llamar a OpenAI:", repr(e))
        return "", [], []

    try:
        raw = response.output[0].content[0].text
    except Exception as e:
        print("[Vision-Imaging] Error extrayendo texto de respuesta:", repr(e))
        return "", [], []

    try:
        data = json.loads(raw)
    except Exception as e:
        print("[Vision-Imaging] Error parseando JSON de IA:", repr(e))
        return "", [], []

    summary = str(data.get("summary", "") or "").strip()
    differential = _ensure_list_of_str(data.get("differential", []))
    patterns = _ensure_list_of_str(data.get("patterns", []))

    return summary, differential, patterns
