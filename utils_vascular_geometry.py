import json
from typing import Any, Dict, Optional
from openai import OpenAI

SYSTEM_PROMPT_VASCULAR_GEOMETRY = """
Eres un asistente de visión para ecografía vascular.
NO diagnostiques. NO emitas conclusiones clínicas.
Devuelve SOLO un JSON válido y conciso para orientación visual.

Objetivo:
- Identificar el vaso principal visible.
- Proporcionar posición y tamaño aproximados.
- Todo es orientativo.

Formato JSON ESTRICTO:
{
  "profile": "VASCULAR",
  "roi": {"x0":0-1,"y0":0-1,"x1":0-1,"y1":0-1},
  "layers": {
    "skin_end": 0-1,
    "vessel_cx": 0-1,
    "vessel_cy": 0-1,
    "vessel_rx": 0-0.5,
    "vessel_ry": 0-0.5
  },
  "label": {"text": "Vaso (orientativo)"},
  "confidence": 0-1
}
"""

def _clamp(v: Any, lo: float, hi: float, default: float) -> float:
    try:
        f = float(v)
    except Exception:
        return default
    if f < lo:
        return lo
    if f > hi:
        return hi
    return f

def analyze_vascular_geometry(
    *,
    client: OpenAI,
    image_url: str,
    model: str,
    system_prompt: str = SYSTEM_PROMPT_VASCULAR_GEOMETRY,
    extra_context: Optional[str] = None,
) -> Dict[str, Any]:
    user_text = "Analiza la imagen ecográfica vascular y devuelve SOLO JSON orientativo."
    if extra_context:
        user_text += f" Contexto adicional: {extra_context}"

    user_content = [
        {"type": "text", "text": user_text},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": [{"type": "text", "text": system_prompt.strip()}]},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )

        msg = resp.choices[0].message.content
        raw = msg[0].text if isinstance(msg, list) and msg else str(msg)
        data = json.loads(raw)
    except Exception as e:
        return {
            "profile": "VASCULAR",
            "roi": {"x0": 0.10, "y0": 0.10, "x1": 0.95, "y1": 0.85},
            "layers": {
                "skin_end": 0.06,
                "vessel_cx": 0.5,
                "vessel_cy": 0.5,
                "vessel_rx": 0.10,
                "vessel_ry": 0.08,
            },
            "label": {"text": "Vaso (orientativo)"},
            "confidence": 0.0,
            "method": "fallback",
            "error": repr(e),
        }

    roi = data.get("roi", {})
    layers = data.get("layers", {})

    return {
        "profile": "VASCULAR",
        "roi": {
            "x0": _clamp(roi.get("x0"), 0.0, 1.0, 0.10),
            "y0": _clamp(roi.get("y0"), 0.0, 1.0, 0.10),
            "x1": _clamp(roi.get("x1"), 0.0, 1.0, 0.95),
            "y1": _clamp(roi.get("y1"), 0.0, 1.0, 0.85),
        },
        "layers": {
            "skin_end": _clamp(layers.get("skin_end"), 0.0, 1.0, 0.06),
            "vessel_cx": _clamp(layers.get("vessel_cx"), 0.0, 1.0, 0.5),
            "vessel_cy": _clamp(layers.get("vessel_cy"), 0.0, 1.0, 0.5),
            "vessel_rx": _clamp(layers.get("vessel_rx"), 0.02, 0.5, 0.10),
            "vessel_ry": _clamp(layers.get("vessel_ry"), 0.02, 0.5, 0.08),
        },
        "label": {"text": "Vaso (orientativo)"},
        "confidence": _clamp(data.get("confidence"), 0.0, 1.0, 0.5),
        "method": "vision-vascular-v1",
    }
