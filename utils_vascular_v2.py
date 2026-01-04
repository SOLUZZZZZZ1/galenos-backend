# utils_vascular_v2.py — Vascular V2 (señales + base + oráculo)
import json
from typing import Any, Dict, Optional
from openai import OpenAI

from prompts_vascular_v2 import SYSTEM_PROMPT_VASCULAR_V2_SIGNALS, SYSTEM_PROMPT_VASCULAR_V2_ORACLE

def _safe_list(obj):
    return obj if isinstance(obj, list) else []

def _clamp01(v, default=0.0):
    try:
        x = float(v)
    except Exception:
        return default
    if x < 0: return 0.0
    if x > 1: return 1.0
    return x

def analyze_vascular_v2_signals(
    *,
    client: OpenAI,
    image_url: str,
    model: str,
    extra_context: Optional[str] = None,
) -> Dict[str, Any]:
    user_text = "Analiza la imagen vascular y devuelve señales estructuradas (hechos + patrones), sin diagnóstico."
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
                {"role": "system", "content": [{"type": "text", "text": SYSTEM_PROMPT_VASCULAR_V2_SIGNALS.strip()}]},
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
            "quality_notes": [{"type":"low_quality","confidence":0.0,"evidence":f"error:{repr(e)}"}],
            "_error": repr(e),
        }

    out = {
        "facts_visible": _safe_list(data.get("facts_visible")),
        "patterns_detected": _safe_list(data.get("patterns_detected")),
        "comparisons": _safe_list(data.get("comparisons")),
        "quality_notes": _safe_list(data.get("quality_notes")),
    }

    for key in ("facts_visible","patterns_detected","comparisons","quality_notes"):
        arr = out.get(key, [])
        norm = []
        for it in arr:
            if not isinstance(it, dict): 
                continue
            it2 = dict(it)
            it2["confidence"] = _clamp01(it2.get("confidence", 0.5), 0.5)
            it2["type"] = str(it2.get("type","")).strip()
            it2["evidence"] = str(it2.get("evidence","")).strip()
            norm.append(it2)
        out[key] = norm
    return out

def build_vascular_v2_base(signals: Dict[str, Any]) -> Dict[str, Any]:
    facts = []
    patterns = []
    quality = []

    for it in signals.get("facts_visible", []) or []:
        t = (it.get("type") or "").lower()
        c = float(it.get("confidence", 0.0) or 0.0)
        if t == "stent" and c >= 0.55:
            facts.append("Hallazgo estructural: stent vascular visible en el segmento analizado.")
        elif t and c >= 0.75:
            facts.append("Hallazgo estructural: material/implante visible en el segmento analizado.")

    for it in signals.get("patterns_detected", []) or []:
        t = (it.get("type") or "").lower()
        c = float(it.get("confidence", 0.0) or 0.0)
        if t in ("flow_variation","lumen_irregularity","wall_irregularity","texture_change") and c >= 0.55:
            patterns.append("Patrón observado: variación local respecto al segmento/entorno inmediato (orientativo).")
            break

    for it in signals.get("comparisons", []) or []:
        c = float(it.get("confidence", 0.0) or 0.0)
        if c >= 0.60:
            patterns.append("Comparación: diferencia visual entre segmentos proximal y distal (orientativo).")
            break

    for it in signals.get("quality_notes", []) or []:
        c = float(it.get("confidence", 0.0) or 0.0)
        if c >= 0.45:
            quality.append("Nota de calidad: la adquisición/ángulo puede limitar la interpretación completa.")
            break

    oracle_available = bool(facts or patterns or quality)

    return {
        "facts": facts[:2],
        "patterns": patterns[:2],
        "quality": quality[:1],
        "oracle_available": oracle_available,
        "disclaimer": "Interpretación orientativa basada en esta imagen. La valoración final corresponde al profesional responsable.",
    }

def run_vascular_v2_oracle(
    *,
    client: OpenAI,
    model: str,
    signals: Dict[str, Any],
    extra_context: Optional[str] = None,
) -> Dict[str, Any]:
    user_text = "Genera escenarios generales a considerar a partir de estas señales visuales (no diagnóstico)."
    payload = {"signals": signals, "context": extra_context or ""}

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": [{"type": "text", "text": SYSTEM_PROMPT_VASCULAR_V2_ORACLE.strip()}]},
                {"role": "user", "content": [{"type":"text","text": user_text + "\n\n" + json.dumps(payload, ensure_ascii=False)}]},
            ],
            response_format={"type": "json_object"},
        )
        msg = resp.choices[0].message.content
        raw = msg[0].text if isinstance(msg, list) and msg else str(msg)
        data = json.loads(raw)
    except Exception as e:
        return {
            "scenarios": [],
            "disclaimer": "Análisis avanzado no disponible en este momento.",
            "_error": repr(e),
        }

    scenarios = data.get("scenarios", [])
    if not isinstance(scenarios, list):
        scenarios = []
    scenarios = [str(s).strip() for s in scenarios if str(s).strip()]

    disclaimer = str(data.get("disclaimer") or "").strip()
    if not disclaimer:
        disclaimer = "Este análisis es orientativo y no constituye diagnóstico ni recomendación clínica."

    return {"scenarios": scenarios[:5], "disclaimer": disclaimer}
