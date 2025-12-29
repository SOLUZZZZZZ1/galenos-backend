# utils_msk_geometry.py — IA geométrica MSK (Galenos)
#
# Devuelve geometría para overlay MSK en ecografías: ROI + fascia_y + confidence.
# NO diagnóstico. NO texto clínico.

import json
from typing import Any, Dict, Optional
from openai import OpenAI


SYSTEM_PROMPT_MSK_GEOMETRY = """
Eres un asistente de visión para geometría en ecografía musculoesquelética (MSK).
NO diagnostiques. NO des recomendaciones clínicas.

Devuelve SIEMPRE un JSON válido EXACTO con esta estructura:

{
  "roi": { "x0": 0.0-1.0, "y0": 0.0-1.0, "x1": 0.0-1.0, "y1": 0.0-1.0 },
  "layers": {
    "skin_end": 0.0-1.0,
    "subc_end": 0.0-1.0,
    "fascia_y": 0.0-1.0
  },
  "label": { "muscle_offset": 0.0-10.0 },
  "rotation_deg": -15.0-15.0,
  "confidence": 0.0-1.0
}

REGLAS:
- roi delimita la zona anatómica útil (excluye bordes negros, textos, escalas).
- fascia_y es la coordenada vertical relativa (dentro de roi) donde empieza el músculo.
- skin_end y subc_end son posiciones relativas (dentro de roi) para guías didácticas.
- rotation_deg: si ves la imagen inclinada, estima grados (pequeños).
- confidence: baja si hay baja calidad, mucho ruido, o no es MSK.
- Si no puedes estimar, usa valores razonables y confidence baja (<=0.4).
"""


def _clamp01(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return float(default)
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
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
        user_text += f" Contexto adicional: {extra_context}"

    user_content = [
        {"type": "text", "text": user_text},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": [{"type": "text", "text": (system_prompt or "").strip()}]},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )
    except Exception as e:
        return {
            "roi": {"x0": 0.10, "y0": 0.10, "x1": 0.95, "y1": 0.84},
            "layers": {"skin_end": 0.06, "subc_end": 0.22, "fascia_y": 0.30},
            "label": {"muscle_offset": 1.6},
            "rotation_deg": 0.0,
            "confidence": 0.0,
            "method": "vision-v1",
            "error": f"openai_call_failed: {repr(e)}",
        }

    try:
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
            "error": f"json_parse_failed: {repr(e)}",
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
        "label": {
            "muscle_offset": float(label.get("muscle_offset", 1.6) or 1.6),
        },
        "rotation_deg": float(data.get("rotation_deg", 0.0) or 0.0),
        "confidence": float(data.get("confidence", 0.5) or 0.5),
        "method": "vision-v1",
    }

    # Ensure sane ordering
    if out["roi"]["x1"] <= out["roi"]["x0"]:
        out["roi"]["x1"] = min(1.0, out["roi"]["x0"] + 0.85)
    if out["roi"]["y1"] <= out["roi"]["y0"]:
        out["roi"]["y1"] = min(1.0, out["roi"]["y0"] + 0.74)

    # Ensure layer monotonicity inside roi
    skin_end = out["layers"]["skin_end"]
    subc_end = out["layers"]["subc_end"]
    fascia_y = out["layers"]["fascia_y"]
    if subc_end < skin_end:
        out["layers"]["subc_end"] = min(1.0, skin_end + 0.10)
    if fascia_y < out["layers"]["subc_end"]:
        out["layers"]["fascia_y"] = min(1.0, out["layers"]["subc_end"] + 0.08)

    # Clamp confidence
    if out["confidence"] < 0.0:
        out["confidence"] = 0.0
    if out["confidence"] > 1.0:
        out["confidence"] = 1.0

    return out
