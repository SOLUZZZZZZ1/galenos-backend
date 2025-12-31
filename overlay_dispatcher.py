from ui_profiles import UIProfile
from utils_msk_geometry import analyze_msk_geometry, SYSTEM_PROMPT_MSK_GEOMETRY

# ✅ NUEVO: VASCULAR
from utils_vascular_geometry import analyze_vascular_geometry, SYSTEM_PROMPT_VASCULAR_GEOMETRY


def generate_overlay(*, profile: UIProfile, **kwargs) -> dict:
    if profile == UIProfile.MSK:
        return analyze_msk_geometry(system_prompt=SYSTEM_PROMPT_MSK_GEOMETRY, **kwargs)

    # ✅ NUEVO: VASCULAR
    if profile == UIProfile.VASCULAR:
        return analyze_vascular_geometry(system_prompt=SYSTEM_PROMPT_VASCULAR_GEOMETRY, **kwargs)

    # Próximos perfiles se implementan aquí
    raise ValueError(f"Perfil no soportado: {profile}")
