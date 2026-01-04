from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db

from utils_vascular_v2 import analyze_vascular_v2_signals, build_vascular_v2_base, run_vascular_v2_oracle
from utils_vascular_geometry import analyze_vascular_geometry, SYSTEM_PROMPT_VASCULAR_GEOMETRY
from utils_roi_apply import normalize_roi, image_url_to_pil, crop_pil_to_roi, pil_to_data_url_png, remap_overlay_vascular

from imaging import _get_openai_client, _get_imaging_owned, _file_path_for_front

router = APIRouter(prefix="/imaging", tags=["Imaging-Vascular-V2"])


class VascularV2OracleRequest(BaseModel):
    context: Optional[str] = None


@router.post("/vascular-v2/{imaging_id}")
def vascular_v2_analyze(
    imaging_id: int,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = _get_imaging_owned(db, imaging_id=imaging_id, doctor_id=current_user.id)
    if not row:
        raise HTTPException(404, "Imagen no encontrada o no pertenece al usuario.")

    img_url = _file_path_for_front(row.get("file_path"), user_id=current_user.id, record_id=row.get("id"), kind="imaging")
    if not img_url:
        raise HTTPException(500, "No se ha podido generar URL de la imagen.")

    client = _get_openai_client()
    model = os.getenv("GALENOS_VISION_MODEL", "gpt-4o")

    roi = normalize_roi(row.get("roi_json"))
    image_url_for_ai = img_url
    roi_used = None
    if roi:
        try:
            img_full = image_url_to_pil(img_url)
            img_crop = crop_pil_to_roi(img_full, roi)
            image_url_for_ai = pil_to_data_url_png(img_crop)
            roi_used = roi
        except Exception:
            roi_used = None
            image_url_for_ai = img_url

    extra_context = payload.get("context") if isinstance(payload, dict) else None

    signals = analyze_vascular_v2_signals(client=client, image_url=image_url_for_ai, model=model, extra_context=extra_context)
    base = build_vascular_v2_base(signals)

    vascular_overlay = None
    try:
        geom = analyze_vascular_geometry(client=client, image_url=image_url_for_ai, model=model, system_prompt=SYSTEM_PROMPT_VASCULAR_GEOMETRY)
        if roi_used:
            geom = remap_overlay_vascular(geom, roi_used)
        vascular_overlay = geom
    except Exception:
        vascular_overlay = None

    return {
        "imaging_id": imaging_id,
        "base": base,
        "signals": signals,
        "oracle_available": bool(base.get("oracle_available")),
        "visual": {"vascular_overlay": vascular_overlay},
    }


@router.post("/vascular-v2/{imaging_id}/oracle")
def vascular_v2_oracle(
    imaging_id: int,
    req: VascularV2OracleRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = _get_imaging_owned(db, imaging_id=imaging_id, doctor_id=current_user.id)
    if not row:
        raise HTTPException(404, "Imagen no encontrada o no pertenece al usuario.")

    img_url = _file_path_for_front(row.get("file_path"), user_id=current_user.id, record_id=row.get("id"), kind="imaging")
    if not img_url:
        raise HTTPException(500, "No se ha podido generar URL de la imagen.")

    client = _get_openai_client()
    model = os.getenv("GALENOS_VISION_MODEL", "gpt-4o")

    roi = normalize_roi(row.get("roi_json"))
    image_url_for_ai = img_url
    if roi:
        try:
            img_full = image_url_to_pil(img_url)
            img_crop = crop_pil_to_roi(img_full, roi)
            image_url_for_ai = pil_to_data_url_png(img_crop)
        except Exception:
            image_url_for_ai = img_url

    signals = analyze_vascular_v2_signals(client=client, image_url=image_url_for_ai, model=model, extra_context=req.context)
    oracle = run_vascular_v2_oracle(client=client, model=model, signals=signals, extra_context=req.context)

    return {
        "imaging_id": imaging_id,
        "scenarios": oracle.get("scenarios", []),
        "disclaimer": oracle.get("disclaimer", ""),
    }
