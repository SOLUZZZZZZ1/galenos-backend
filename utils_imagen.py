# utils_imagen.py — IA Vision para imágenes médicas (TAC / RM / RX / ECO) usando chat.completions

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
    """Envía una imagen médica a GPT-4o Vision usando chat.completions.

    Devuelve:
      - summary: descripción orientativa prudente
      - differential: posibles causas generales a valorar (lista de strings)
      - patterns: lista de patrones visuales detectados (lista de strings)
    """

    if not image_b64:
        return "", [], []

    user_text = "Analiza la siguiente imagen médica de forma prudente."
    if extra_context:
        user_text += f" Contexto adicional proporcionado por el médico: {extra_context}."

    user_content: List[dict] = [
        {"type": "text", "text": user_text},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{image_b64}",
            },
        },
    ]

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
        print("[Vision-Imaging] Error al llamar a OpenAI:", repr(e))
        return "", [], []

    try:
        msg_content = response.choices[0].message.content
        if isinstance(msg_content, list) and msg_content:
            raw = msg_content[0].text
        else:
            raw = str(msg_content)
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
