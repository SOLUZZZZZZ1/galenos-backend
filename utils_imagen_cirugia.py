# utils_imagen_cirugia.py — IA Vision para cirugía (descriptivo, NO radiológico)
import base64
from typing import Optional
from openai import OpenAI

def analyze_surgical_photo(
    client: OpenAI,
    image_bytes: bytes,
    model: str,
    system_prompt: str,
    extra_context: Optional[str] = None,
) -> str:
    if not image_bytes:
        return ""

    b64 = base64.b64encode(image_bytes).decode("utf-8")

    user_text = "Describe esta imagen clínica quirúrgica de forma objetiva y prudente siguiendo la estructura indicada."
    if extra_context:
        user_text += f" Contexto aportado por el médico: {extra_context}."

    user_content = [
        {"type": "text", "text": user_text},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
                {"role": "user", "content": user_content},
            ],
        )
    except Exception as e:
        print("[Vision-Cosmetic] Error al llamar a OpenAI:", repr(e))
        return ""

    try:
        msg = resp.choices[0].message.content
        if isinstance(msg, list) and msg:
            return str(msg[0].text or "").strip()
        return str(msg or "").strip()
    except Exception as e:
        print("[Vision-Cosmetic] Error extrayendo respuesta:", repr(e))
        return ""
