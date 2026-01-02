from ui_profiles import UIProfile
from utils_roi_apply import normalize_roi, image_url_to_pil, crop_pil_to_roi, pil_to_data_url_png, remap_overlay_msk, remap_overlay_vascular
from utils_msk_geometry import analyze_msk_geometry, SYSTEM_PROMPT_MSK_GEOMETRY

# ✅ NUEVO: VASCULAR
from utils_vascular_geometry import analyze_vascular_geometry, SYSTEM_PROMPT_VASCULAR_GEOMETRY


def generate_overlay(*, profile: UIProfile, **kwargs) -> dict:
    # ROI V1.1: aplicar ROI a overlays (invisible)
    roi_raw = kwargs.pop("roi", None)
    roi = normalize_roi(roi_raw)
    roi_used = None
    if roi and isinstance(kwargs.get("image_url"), str) and kwargs["image_url"]:
        try:
            img_full = image_url_to_pil(kwargs["image_url"])
            img_crop = crop_pil_to_roi(img_full, roi)
            kwargs["image_url"] = pil_to_data_url_png(img_crop)
            roi_used = roi
        except Exception:
            roi_used = None
    
    if profile == UIProfile.MSK:
        out = analyze_msk_geometry(system_prompt=SYSTEM_PROMPT_MSK_GEOMETRY, **kwargs)
        if roi_used:
            try:
                out = remap_overlay_msk(out, roi_used)
            except Exception:
                pass
        return out

    # ✅ NUEVO: VASCULAR
    if profile == UIProfile.VASCULAR:
        out = analyze_vascular_geometry(system_prompt=SYSTEM_PROMPT_VASCULAR_GEOMETRY, **kwargs)
        if roi_used:
            try:
                out = remap_overlay_vascular(out, roi_used)
            except Exception:
                pass
        return out

    # Próximos perfiles se implementan aquí
    raise ValueError(f"Perfil no soportado: {profile}")
