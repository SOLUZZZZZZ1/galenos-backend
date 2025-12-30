import json
from typing import Any, Dict, Optional
from openai import OpenAI

SYSTEM_PROMPT_MSK_GEOMETRY = """
Eres un asistente de visión para geometría en ecografía musculoesquelética (MSK).
NO diagnostiques. Devuelve SOLO JSON.

Formato JSON estricto:
{
  "roi": {"x0":0-1,"y0":0-1,"x1":0-1,"y1":0-1},
  "layers": {"skin_end":0-1,"subc_end":0-1,"fascia_y":0-1},
  "label": {"muscle_offset": 0-10},
  "rotation_deg": -15-15,
  "confidence": 0-1
}
"""


def _clamp01(x: Any, default: float) -> float:
    try:
        v = float(x)
    except Exception:
        return default
    if v < 0: return 0.0
    if v > 1: return 1.0
    return v


def analyze_msk_geometry(
    *,
    client: OpenAI,
    image_url: str,
    model: str,
    system_prompt: str = SYSTEM_PROMPT_MSK_GEOMETRY,
    extra_context: Optional[str] = None,
) -> Dict[str, Any]:
    user_text = "Analiza la geometría MSK y devuelve SOLO JSON."
    if extra_context:
        user_text += f" Contexto: {extra_context}"

    user_content = [
        {"type": "text", "text": user_text},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": [{"type": "text", "text": (system_prompt or '').strip()}]},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )
        msg_content = resp.choices[0].message.content
        raw = msg_content[0].text if isinstance(msg_content, list) and msg_content else str(msg_content)
        data = json.loads(raw)
    except Exception as e:
        return {
            "roi": {"x0": 0.10, "y0": 0.10, "x1": 0.95, "y1": 0.84},
            "layers": {"skin_end": 0.06, "subc_end": 0.22, "fascia_y": 0.30},
            "label": {"muscle_offset": 1.6},
            "rotation_deg": 0.0,
            "confidence": 0.0,
            "method": "vision-v1",
            "error": repr(e),
        }

    roi = data.get("roi") or {}
    layers = data.get("layers") or {}
    label = data.get("label") or {}

    out = {
        "roi": {
            "x0": _clamp01(roi.get("x0"), 0.10),
            "y0": _clamp01(roi.get("y0"), 0.10),
            "x1": _clamp01(roi.get("x1"), 0.95),
            "y1": _clamp01(roi.get("y1"), 0.84),
        },
        "layers": {
            "skin_end": _clamp01(layers.get("skin_end"), 0.06),
            "subc_end": _clamp01(layers.get("subc_end"), 0.22),
            "fascia_y": _clamp01(layers.get("fascia_y"), 0.30),
        },
        "label": {"muscle_offset": float(label.get("muscle_offset", 1.6) or 1.6)},
        "rotation_deg": float(data.get("rotation_deg", 0.0) or 0.0),
        "confidence": float(data.get("confidence", 0.5) or 0.5),
        "method": "vision-v1",
    }
    return out
