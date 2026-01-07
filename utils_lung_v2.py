# utils_lung_v2.py — Pulmón V2 (señales estructuradas, sin diagnóstico)

import json
from typing import Any, Dict, Optional
from openai import OpenAI

from prompts_lung_v2 import SYSTEM_PROMPT_LUNG_V2_SIGNALS


def _safe_list(obj):
    return obj if isinstance(obj, list) else []


def _clamp01(v, default=0.5):
    try:
        x = float(v)
    except Exception:
        return default
    if x < 0:
        return 0.0
    if x > 1:
        return 1.0
    return x


def analyze_lung_v2_signals(
    *,
    client: OpenAI,
    image_url: str,
    model: str,
    extra_context: Optional[str] = None,
) -> Dict[str, Any]:
    user_text = (
        "Analiza la imagen torácica y devuelve señales estructuradas "
        "(hechos y patrones), sin diagnóstico."
    )
    if extra_context:
        user_text += f" Contexto clínico: {extra_context}"

    user_content = [
        {"type": "text", "text": user_text},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": [{"type": "text", "text": SYSTEM_PROMPT_LUNG_V2_SIGNALS.strip()}]},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )
        msg = resp.choices[0].message.content
        raw = msg[0].text if isinstance(msg, list) and msg else str(msg)
        data = json.loads(raw)
    except Exception as e:
        return {
            "facts_visible": [],
            "patterns_detected": [],
            "comparisons": [],
            "quality_notes": [{"type": "low_quality", "confidence": 0.0, "evidence": f"error:{repr(e)}"}],
            "_error": repr(e),
        }

    out = {
        "facts_visible": _safe_list(data.get("facts_visible")),
        "patterns_detected": _safe_list(data.get("patterns_detected")),
        "comparisons": _safe_list(data.get("comparisons")),
        "quality_notes": _safe_list(data.get("quality_notes")),
    }

    for key in ("facts_visible", "patterns_detected", "comparisons", "quality_notes"):
        arr = out.get(key, [])
        norm = []
        for it in arr:
            if not isinstance(it, dict):
                continue
            it2 = dict(it)
            it2["type"] = str(it2.get("type", "")).strip()
            it2["evidence"] = str(it2.get("evidence", "")).strip()
            it2["confidence"] = _clamp01(it2.get("confidence", 0.5))
            norm.append(it2)
        out[key] = norm

    return out
