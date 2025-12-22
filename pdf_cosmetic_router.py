# pdf_cosmetic_router.py — PDF quirúrgico Antes/Después (V1) · Galenos
# Endpoint: POST /pdf/cosmetic-compare
# - Genera un PDF con 2 imágenes (ANTES / DESPUÉS) + texto comparativo + nota opcional
# - NO guarda el PDF por defecto (solo descarga)
# - Protegido por JWT (médico) y ownership (patient.doctor_id)
#
# Dependencias: PyMuPDF (fitz) ya está en el backend (pymupdf).

from typing import Optional
from datetime import datetime
import os
import urllib.request
import io

import fitz  # PyMuPDF
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user
from models import Imaging, Patient, User
import storage_b2

router = APIRouter(prefix="/pdf", tags=["PDF-Cosmetic"])


class CosmeticComparePdfIn(BaseModel):
    pre_image_id: int
    post_image_id: int
    compare_text: str
    note: Optional[str] = None


def _fetch_image_bytes(file_key: str) -> bytes:
    if not file_key:
        return b""
    try:
        url = storage_b2.generate_presigned_url(file_key=file_key, expires_seconds=600)
        with urllib.request.urlopen(url) as r:
            return r.read()
    except Exception as e:
        print("[PDF-Cosmetic] Error descargando imagen:", repr(e))
        return b""


def _now_utc_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def _load_logo_bytes() -> bytes:
    # Opcional: GALENOS_LOGO_URL (http/https) o GALENOS_LOGO_B2_KEY
    url = os.getenv("GALENOS_LOGO_URL") or ""
    key = os.getenv("GALENOS_LOGO_B2_KEY") or ""
    if key:
        return _fetch_image_bytes(key)
    if url:
        try:
            with urllib.request.urlopen(url) as r:
                return r.read()
        except Exception:
            return b""
    return b""


@router.post("/cosmetic-compare")
def generate_cosmetic_compare_pdf(
    payload: CosmeticComparePdfIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pre = (
        db.query(Imaging)
        .join(Patient, Patient.id == Imaging.patient_id)
        .filter(Imaging.id == payload.pre_image_id, Patient.doctor_id == current_user.id)
        .first()
    )
    post = (
        db.query(Imaging)
        .join(Patient, Patient.id == Imaging.patient_id)
        .filter(Imaging.id == payload.post_image_id, Patient.doctor_id == current_user.id)
        .first()
    )

    if not pre or not post:
        raise HTTPException(404, "Imagen 'Antes' o 'Después' no encontrada o no autorizada.")

    if not (str(pre.type or "").upper().startswith("COSMETIC") and str(post.type or "").upper().startswith("COSMETIC")):
        raise HTTPException(400, "Las imágenes deben ser COSMETIC_* para generar el PDF quirúrgico.")

    pre_bytes = _fetch_image_bytes(pre.file_path)
    post_bytes = _fetch_image_bytes(post.file_path)
    if not pre_bytes or not post_bytes:
        raise HTTPException(500, "No se pudieron cargar las imágenes desde almacenamiento.")

    compare_text = (payload.compare_text or "").strip()
    if not compare_text:
        raise HTTPException(400, "compare_text está vacío.")

    note = (payload.note or "").strip()

    # ----------
    # Crear PDF (A4) con PyMuPDF
    # ----------
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4 aprox (pt)
    W = page.rect.width
    H = page.rect.height

    margin = 36
    y = margin

    # Logo pequeño o fallback a texto
    logo_bytes = _load_logo_bytes()
    x_title = margin
    if logo_bytes:
        try:
            page.insert_image(fitz.Rect(margin, y, margin + 28, y + 28), stream=logo_bytes)
            x_title = margin + 34
        except Exception:
            x_title = margin

    # Cabecera
    page.insert_text((x_title, y + 14), "Galenos", fontsize=15, fontname="helv", color=(0, 0, 0))
    page.insert_text((W - margin - 160, y + 16), _now_utc_str(), fontsize=9, fontname="helv", color=(0.35, 0.35, 0.35))
    y += 44

    page.insert_text((margin, y), "Comparativa quirúrgica Antes / Después", fontsize=13, fontname="helv", color=(0, 0, 0))
    y += 18

    # Imágenes lado a lado
    gap = 16
    imgW = (W - margin * 2 - gap) / 2
    imgH = 220

    page.insert_text((margin, y), "ANTES", fontsize=10, fontname="helv", color=(0.2, 0.2, 0.2))
    page.insert_text((margin + imgW + gap, y), "DESPUÉS", fontsize=10, fontname="helv", color=(0.2, 0.2, 0.2))

    rect_pre = fitz.Rect(margin, y + 14, margin + imgW, y + 14 + imgH)
    rect_post = fitz.Rect(margin + imgW + gap, y + 14, margin + imgW + gap + imgW, y + 14 + imgH)

    try:
        page.insert_image(rect_pre, stream=pre_bytes, keep_proportion=True)
    except Exception:
        page.insert_textbox(rect_pre, "No se pudo renderizar la imagen ANTES.", fontsize=10, fontname="helv", color=(0.6, 0, 0))
    try:
        page.insert_image(rect_post, stream=post_bytes, keep_proportion=True)
    except Exception:
        page.insert_textbox(rect_post, "No se pudo renderizar la imagen DESPUÉS.", fontsize=10, fontname="helv", color=(0.6, 0, 0))

    y = rect_pre.y1 + 18

    # Texto comparativo IA
    page.insert_text((margin, y), "Descripción comparativa (orientativa)", fontsize=11, fontname="helv", color=(0, 0, 0))
    y += 12

    box = fitz.Rect(margin, y, W - margin, y + 170)
    page.draw_rect(box, color=(0.85, 0.85, 0.85), fill=(0.97, 0.97, 0.98), width=0.8)
    page.insert_textbox(
        fitz.Rect(box.x0 + 10, box.y0 + 8, box.x1 - 10, box.y1 - 8),
        compare_text,
        fontsize=9.5,
        fontname="helv",
        color=(0.1, 0.1, 0.1),
        align=0,
    )
    y = box.y1 + 16

    # Nota del cirujano (solo si existe)
    if note:
        page.insert_text((margin, y), "Nota del cirujano", fontsize=11, fontname="helv", color=(0, 0, 0))
        y += 12
        note_box = fitz.Rect(margin, y, W - margin, y + 110)
        page.draw_rect(note_box, color=(0.90, 0.90, 0.90), fill=(1, 1, 1), width=0.8)
        page.insert_textbox(
            fitz.Rect(note_box.x0 + 10, note_box.y0 + 8, note_box.x1 - 10, note_box.y1 - 8),
            note,
            fontsize=9.5,
            fontname="helv",
            color=(0.1, 0.1, 0.1),
            align=0,
        )

    # Disclaimer pie
    disclaimer = (
        "Documento de apoyo descriptivo.\n"
        "No constituye diagnóstico ni garantía de resultado.\n"
        "La interpretación clínica y la decisión final corresponden al médico responsable."
    )
    foot = fitz.Rect(margin, H - 90, W - margin, H - 36)
    page.insert_textbox(foot, disclaimer, fontsize=8.5, fontname="helv", color=(0.35, 0.35, 0.35), align=0)

    pdf_bytes = doc.tobytes()
    doc.close()

    filename = f"Galenos_Comparativa_{payload.pre_image_id}_{payload.post_image_id}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
