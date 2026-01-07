# lung_v2_router.py — Pulmón V2 (RX / TAC / ECO)

import os
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db

from imaging import _get_openai_client, _get_imaging_owned, _file_path_for_front
from utils_lung_v2 import analyze_lung_v2_signals

router = APIRouter(prefix="/imaging", tags=["Imaging-Lung-V2"])


@router.post("/lung-v2/{imaging_id}")
def lung_v2_analyze(
    imaging_id: int,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = _get_imaging_owned(db, imaging_id=imaging_id, doctor_id=current_user.id)
    if not row:
        raise HTTPException(404, "Imagen no encontrada o no pertenece al usuario.")

    img_url = _file_path_for_front(
        row.get("file_path"),
        user_id=current_user.id,
        record_id=row.get("id"),
        kind="imaging",
    )
    if not img_url:
        raise HTTPException(500, "No se ha podido generar URL de la imagen.")

    client = _get_openai_client()
    model = os.getenv("GALENOS_VISION_MODEL", "gpt-4o")
    extra_context = payload.get("context") if isinstance(payload, dict) else None

    signals = analyze_lung_v2_signals(
        client=client,
        image_url=img_url,
        model=model,
        extra_context=extra_context,
    )

    return {
        "imaging_id": imaging_id,
        "signals": signals,
        "disclaimer": "Análisis descriptivo orientativo. No constituye diagnóstico.",
    }
