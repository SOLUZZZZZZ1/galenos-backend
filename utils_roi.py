from __future__ import annotations

"""
utils_roi.py — ROI determinista (Region of Interest) para imágenes en Galenos.pro

- Detecta región clínica "real" (textura/contraste) y descarta fondos/pareder/UI.
- No es diagnóstico. No usa IA.
- Devuelve ROI normalizado 0..1.
"""

import base64
import io
from typing import Any, Dict

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

from PIL import Image


def _clamp01(v: float) -> float:
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return float(v)


def _default_roi() -> Dict[str, Any]:
    return {
        "version": "ROI_V1",
        "x0": 0.02,
        "y0": 0.02,
        "x1": 0.98,
        "y1": 0.98,
        "method": "fallback_fullframe",
        "confidence": 0.0,
    }


def _decode_b64_to_pil(image_b64: str) -> Image.Image | None:
    try:
        raw = base64.b64decode(image_b64)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        return None


def _resize_keep_aspect(img: Image.Image, target_w: int = 512) -> Image.Image:
    w, h = img.size
    if w <= target_w:
        return img
    ratio = target_w / float(w)
    nh = max(1, int(h * ratio))
    return img.resize((target_w, nh), Image.BILINEAR)


def _block_variance(gray_arr, block: int = 16):
    H, W = gray_arr.shape
    Hb = max(1, H // block)
    Wb = max(1, W // block)
    Hc = Hb * block
    Wc = Wb * block
    a = gray_arr[:Hc, :Wc]
    a = a.reshape(Hb, block, Wb, block)
    return a.var(axis=(1, 3))


def detect_roi_from_b64(image_b64: str) -> Dict[str, Any]:
    img = _decode_b64_to_pil(image_b64)
    if img is None or np is None:
        return _default_roi()

    try:
        orig_w, orig_h = img.size
        small = _resize_keep_aspect(img, 512)
        sw, sh = small.size

        g = small.convert("L")
        arr = np.asarray(g).astype("float32")

        block = 16
        var_map = _block_variance(arr, block=block)

        thr = float(np.percentile(var_map, 70))
        mask = var_map > thr

        Hb, Wb = mask.shape
        visited = np.zeros_like(mask, dtype=bool)

        best = None
        best_count = 0

        def neigh(r, c):
            if r > 0: yield r - 1, c
            if r + 1 < Hb: yield r + 1, c
            if c > 0: yield r, c - 1
            if c + 1 < Wb: yield r, c + 1

        for r in range(Hb):
            for c in range(Wb):
                if not mask[r, c] or visited[r, c]:
                    continue
                stack = [(r, c)]
                visited[r, c] = True
                coords = []
                while stack:
                    rr, cc = stack.pop()
                    coords.append((rr, cc))
                    for nr, nc in neigh(rr, cc):
                        if mask[nr, nc] and not visited[nr, nc]:
                            visited[nr, nc] = True
                            stack.append((nr, nc))
                if len(coords) > best_count:
                    best_count = len(coords)
                    best = coords

        if not best or best_count < 6:
            return _default_roi()

        rs = [p[0] for p in best]
        cs = [p[1] for p in best]
        r0, r1 = min(rs), max(rs)
        c0, c1 = min(cs), max(cs)

        # bbox en px del SMALL
        x0_s = c0 * block
        y0_s = r0 * block
        x1_s = (c1 + 1) * block
        y1_s = (r1 + 1) * block

        # margen
        margin_pct = 0.03
        mx = int(sw * margin_pct)
        my = int(sh * margin_pct)
        x0_s = max(0, x0_s - mx)
        y0_s = max(0, y0_s - my)
        x1_s = min(sw, x1_s + mx)
        y1_s = min(sh, y1_s + my)

        # SMALL -> ORIGINAL
        scale_x = orig_w / float(sw)
        scale_y = orig_h / float(sh)
        x0 = x0_s * scale_x
        y0 = y0_s * scale_y
        x1 = x1_s * scale_x
        y1 = y1_s * scale_y

        out = {
            "version": "ROI_V1",
            "x0": _clamp01(x0 / orig_w),
            "y0": _clamp01(y0 / orig_h),
            "x1": _clamp01(x1 / orig_w),
            "y1": _clamp01(y1 / orig_h),
            "method": "texture_variance",
            "confidence": float(min(1.0, best_count / 120.0)),
        }

        if out["x1"] - out["x0"] < 0.2 or out["y1"] - out["y0"] < 0.2:
            return _default_roi()

        return out
    except Exception:
        return _default_roi()
