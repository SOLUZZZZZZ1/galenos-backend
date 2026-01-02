from __future__ import annotations

import base64
import io
from typing import Any, Dict

import httpx
from PIL import Image


def _clamp01(v: float) -> float:
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return float(v)


def normalize_roi(roi: Dict[str, Any] | None) -> Dict[str, float] | None:
    if not isinstance(roi, dict):
        return None
    try:
        x0 = _clamp01(float(roi.get("x0", 0.0)))
        y0 = _clamp01(float(roi.get("y0", 0.0)))
        x1 = _clamp01(float(roi.get("x1", 1.0)))
        y1 = _clamp01(float(roi.get("y1", 1.0)))
        if x1 - x0 < 0.05 or y1 - y0 < 0.05:
            return None
        return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
    except Exception:
        return None


def image_url_to_pil(image_url: str, timeout: float = 20.0) -> Image.Image:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(image_url)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")


def pil_to_data_url_png(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return "data:image/png;base64," + b64


def crop_pil_to_roi(img: Image.Image, roi: Dict[str, float]) -> Image.Image:
    w, h = img.size
    x0 = int(roi["x0"] * w)
    y0 = int(roi["y0"] * h)
    x1 = int(roi["x1"] * w)
    y1 = int(roi["y1"] * h)

    x0 = max(0, min(w - 1, x0))
    y0 = max(0, min(h - 1, y0))
    x1 = max(x0 + 1, min(w, x1))
    y1 = max(y0 + 1, min(h, y1))
    return img.crop((x0, y0, x1, y1))


def remap_x(x: float, roi: Dict[str, float]) -> float:
    return roi["x0"] + float(x) * (roi["x1"] - roi["x0"])


def remap_y(y: float, roi: Dict[str, float]) -> float:
    return roi["y0"] + float(y) * (roi["y1"] - roi["y0"])


def remap_w(w: float, roi: Dict[str, float]) -> float:
    return float(w) * (roi["x1"] - roi["x0"])


def remap_h(h: float, roi: Dict[str, float]) -> float:
    return float(h) * (roi["y1"] - roi["y0"])


def remap_overlay_msk(overlay: Dict[str, Any], roi: Dict[str, float]) -> Dict[str, Any]:
    if not isinstance(overlay, dict):
        return overlay
    out = dict(overlay)

    r = out.get("roi") or {}
    if isinstance(r, dict):
        out["roi"] = {
            "x0": remap_x(r.get("x0", 0.10), roi),
            "y0": remap_y(r.get("y0", 0.10), roi),
            "x1": remap_x(r.get("x1", 0.95), roi),
            "y1": remap_y(r.get("y1", 0.84), roi),
        }

    layers = out.get("layers") or {}
    if isinstance(layers, dict):
        out["layers"] = {
            "skin_end": remap_y(layers.get("skin_end", 0.06), roi),
            "subc_end": remap_y(layers.get("subc_end", 0.22), roi),
            "fascia_y": remap_y(layers.get("fascia_y", 0.30), roi),
        }

    label = out.get("label") or {}
    if isinstance(label, dict):
        try:
            off = float(label.get("muscle_offset", 1.6) or 1.6)
            off_scaled = off * (roi["y1"] - roi["y0"])
            out["label"] = {"muscle_offset": off_scaled}
        except Exception:
            pass

    return out


def remap_overlay_vascular(overlay: Dict[str, Any], roi: Dict[str, float]) -> Dict[str, Any]:
    if not isinstance(overlay, dict):
        return overlay
    out = dict(overlay)

    r = out.get("roi") or {}
    if isinstance(r, dict):
        out["roi"] = {
            "x0": remap_x(r.get("x0", 0.10), roi),
            "y0": remap_y(r.get("y0", 0.10), roi),
            "x1": remap_x(r.get("x1", 0.95), roi),
            "y1": remap_y(r.get("y1", 0.85), roi),
        }

    layers = out.get("layers") or {}
    if isinstance(layers, dict):
        out["layers"] = {
            "skin_end": remap_y(layers.get("skin_end", 0.06), roi),
            "vessel_cx": remap_x(layers.get("vessel_cx", 0.5), roi),
            "vessel_cy": remap_y(layers.get("vessel_cy", 0.5), roi),
            "vessel_rx": remap_w(layers.get("vessel_rx", 0.10), roi),
            "vessel_ry": remap_h(layers.get("vessel_ry", 0.08), roi),
        }

    return out
