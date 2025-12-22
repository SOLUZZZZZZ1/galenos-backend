from typing import Optional
from datetime import datetime
import os
import base64
import hashlib
import urllib.request

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session

from openai import OpenAI

from database import get_db
from auth import get_current_user
from models import Imaging, Patient, User
import crud
import storage_b2
from utils_pdf import convert_pdf_to_images

from prompts_imagen_cirugia import PROMPT_IMAGEN_CIRUGIA
from utils_imagen_cirugia import analyze_surgical_photo

router = APIRouter(prefix="/imaging/cosmetic", tags=["Imaging-Cosmetic"])


def _get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(500, "OPENAI_API_KEY no está configurada.")
    return OpenAI(api_key=api_key)


def _parse_exam_date(exam_date: Optional[str]):
    if not exam_date:
        return None
    try:
        return datetime.strptime(exam_date, "%Y-%m-%d").date()
    except:
        return None


def _ext_from_filename(name: str) -> str:
    name = (name or "").lower().strip()
    if "." in name:
        return name.rsplit(".", 1)[-1]
    return "bin"


def _prepare_preview_b64(file: UploadFile, content: bytes) -> str:
    ct = (file.content_type or "").lower()
    name = (file.filename or "").lower()

    if "pdf" in ct or name.endswith(".pdf"):
        imgs = convert_pdf_to_images(content, max_pages=5, dpi=200)
        if not imgs:
            raise HTTPException(400, "No se han podido extraer imágenes del PDF.")
        return imgs[0]

    if any(name.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff"]):
        return base64.b64encode(content).decode("utf-8")

    imgs = convert_pdf_to_images(content, max_pages=3, dpi=200)
    if imgs:
        return imgs[0]

    raise HTTPException(400, "Formato no soportado para fotografía quirúrgica.")


def _b2_upload_original_and_preview(*, user_id: int, record_id: int, original_filename: str, original_bytes: bytes, preview_b64: str, preview_ext: str = "png"):
    orig_ext = _ext_from_filename(original_filename)
    orig_name = f"original.{orig_ext}"
    orig = storage_b2.upload_bytes(
        user_id=user_id,
        category="imaging",
        object_id=record_id,
        filename=orig_name,
        data=original_bytes,
    )

    try:
        preview_bytes = base64.b64decode(preview_b64)
    except Exception:
        preview_bytes = b""

    prev_name = f"preview.{preview_ext}"
    prev = storage_b2.upload_bytes(
        user_id=user_id,
        category="imaging",
        object_id=record_id,
        filename=prev_name,
        data=preview_bytes if preview_bytes else original_bytes,
    )

    return {
        "preview_key": prev["file_key"],
        "size_bytes": orig["size_bytes"],
        "sha256": orig["sha256"],
        "mime_type": orig["mime_type"],
    }


def _file_path_for_front(db_value: str) -> str:
    if not db_value:
        return None
    if isinstance(db_value, str) and db_value.startswith("data:"):
        return db_value
    try:
        return storage_b2.generate_presigned_url(file_key=db_value, expires_seconds=3600)
    except Exception:
        return db_value


def _fetch_preview_bytes(file_key: str) -> bytes:
    if not file_key:
        return b""
    try:
        url = storage_b2.generate_presigned_url(file_key=file_key, expires_seconds=600)
        with urllib.request.urlopen(url) as r:
            return r.read()
    except Exception as e:
        print("[Cosmetic] Error descargando preview:", repr(e))
        return b""


@router.post("/upload")
async def upload_cosmetic_image(
    patient_id: int = Form(...),
    img_type: str = Form("COSMETIC_PRE"),
    context: Optional[str] = Form(None),
    exam_date: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload para cirugía: guarda y NO analiza automáticamente."""

    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado.")

    if crud.is_storage_quota_exceeded(db, current_user.id):
        raise HTTPException(status_code=402, detail="STORAGE_QUOTA_EXCEEDED")

    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(400, "El fichero está vacío.")

    file_hash = hashlib.sha256(content_bytes).hexdigest()

    existing = crud.get_imaging_by_hash(db, patient.id, file_hash)
    if existing:
        return {
            "id": existing.id,
            "type": existing.type,
            "created_at": existing.created_at,
            "exam_date": existing.exam_date,
            "file_path": _file_path_for_front(existing.file_path),
            "duplicate": True,
            "note": "Duplicado detectado. Si esta imagen fue subida como radiológica, súbela con otro archivo o cambia el tipo desde la ficha (mejora futura).",
        }

    preview_b64 = _prepare_preview_b64(file, content_bytes)

    normalized_type = (img_type or "COSMETIC_PRE").strip().upper()
    if not normalized_type.startswith("COSMETIC"):
        normalized_type = "COSMETIC_PRE"

    exam_date_value = _parse_exam_date(exam_date)

    imaging = crud.create_imaging(
        db=db,
        patient_id=patient.id,
        img_type=normalized_type,
        summary="",
        differential=[],
        file_path=None,
        file_hash=file_hash,
        exam_date=exam_date_value,
    )

    try:
        preview_ext = "png"
        lower_name = (file.filename or "").lower()
        if lower_name.endswith(".jpg") or lower_name.endswith(".jpeg"):
            preview_ext = "jpg"
        elif lower_name.endswith(".png"):
            preview_ext = "png"

        up = _b2_upload_original_and_preview(
            user_id=current_user.id,
            record_id=imaging.id,
            original_filename=file.filename or "cosmetic",
            original_bytes=content_bytes,
            preview_b64=preview_b64,
            preview_ext=preview_ext,
        )
        imaging.file_path = up["preview_key"]
        imaging.size_bytes = up.get("size_bytes", 0) or 0
        db.add(imaging)
        db.commit()
        db.refresh(imaging)
    except Exception as e:
        raise HTTPException(500, f"Error subiendo fichero a almacenamiento: {e}")

    return {
        "id": imaging.id,
        "type": imaging.type,
        "ai_description_draft": getattr(imaging, "ai_description_draft", None),
        "ai_description_updated_at": getattr(imaging, "ai_description_updated_at", None),
        "created_at": imaging.created_at,
        "exam_date": imaging.exam_date,
        "file_path": _file_path_for_front(imaging.file_path),
        "duplicate": False,
        "note": "Imagen guardada. La IA solo se ejecuta si el médico pulsa Analizar imagen.",
    }


@router.post("/{image_id}/analyze")
def analyze_cosmetic_image(
    image_id: int,
    context: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    img = (
        db.query(Imaging)
        .join(Patient, Patient.id == Imaging.patient_id)
        .filter(Imaging.id == image_id, Patient.doctor_id == current_user.id)
        .first()
    )
    if not img:
        raise HTTPException(404, "Imagen no encontrada o no autorizada.")

    itype = (img.type or "").upper().strip()
    if not itype.startswith("COSMETIC"):
        raise HTTPException(400, "Esta imagen no está marcada como COSMETIC_* (cirugía).")

    image_bytes = _fetch_preview_bytes(img.file_path)
    if not image_bytes:
        raise HTTPException(500, "No se pudo cargar la imagen desde almacenamiento.")

    client = _get_openai_client()
    model = os.getenv("GALENOS_VISION_MODEL_COSMETIC") or os.getenv("GALENOS_VISION_MODEL") or "gpt-4o"

    text = analyze_surgical_photo(
        client=client,
        image_bytes=image_bytes,
        model=model,
        system_prompt=PROMPT_IMAGEN_CIRUGIA,
        extra_context=(context or "").strip() or None,
    )
    if not text:
        raise HTTPException(500, "La IA no devolvió un análisis válido.")

    img.ai_description_draft = text
    img.ai_description_updated_at = datetime.utcnow()
    db.add(img)
    db.commit()
    db.refresh(img)

    return {
        "id": img.id,
        "type": img.type,
        "ai_description_draft": img.ai_description_draft,
        "ai_description_updated_at": img.ai_description_updated_at,
        "disclaimer": "Análisis descriptivo. No diagnóstico.",
    }


@router.post("/compare")
def compare_cosmetic_images(
    pre_image_id: int = Form(...),
    post_image_id: int = Form(...),
    context: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pre = (
        db.query(Imaging)
        .join(Patient, Patient.id == Imaging.patient_id)
        .filter(Imaging.id == pre_image_id, Patient.doctor_id == current_user.id)
        .first()
    )
    post = (
        db.query(Imaging)
        .join(Patient, Patient.id == Imaging.patient_id)
        .filter(Imaging.id == post_image_id, Patient.doctor_id == current_user.id)
        .first()
    )
    if not pre or not post:
        raise HTTPException(404, "Imagen 'Antes' o 'Después' no encontrada o no autorizada.")

    if not (str(pre.type or "").upper().startswith("COSMETIC") and str(post.type or "").upper().startswith("COSMETIC")):
        raise HTTPException(400, "Las imágenes deben ser COSMETIC_* para comparativa quirúrgica.")

    pre_bytes = _fetch_preview_bytes(pre.file_path)
    post_bytes = _fetch_preview_bytes(post.file_path)
    if not pre_bytes or not post_bytes:
        raise HTTPException(500, "No se pudieron cargar las imágenes desde almacenamiento.")

    compare_ctx = (
        "Comparación Antes vs Después.\n"
        "Primera imagen: ANTES (preoperatorio).\n"
        "Segunda imagen: DESPUÉS (postoperatorio/seguimiento).\n"
        "Describe cambios visibles de forma prudente y NO valorativa.\n"
        "Incluye advertencias de fiabilidad (luz/ángulo/distancia/calidad).\n"
    )
    extra = (context or "").strip()
    if extra:
        compare_ctx += f"Contexto adicional: {extra}"

    client = _get_openai_client()
    model = os.getenv("GALENOS_VISION_MODEL_COSMETIC") or os.getenv("GALENOS_VISION_MODEL") or "gpt-4o"

    try:
        b64_pre = base64.b64encode(pre_bytes).decode("utf-8")
        b64_post = base64.b64encode(post_bytes).decode("utf-8")

        user_content = [
            {"type": "text", "text": "Genera una comparativa descriptiva siguiendo el prompt del sistema.\n" + compare_ctx},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_pre}"}},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_post}"}},
        ]

        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": [{"type": "text", "text": PROMPT_IMAGEN_CIRUGIA}]},
                {"role": "user", "content": user_content},
            ],
        )

        msg = resp.choices[0].message.content
        if isinstance(msg, list) and msg:
            compare_text = str(msg[0].text or "").strip()
        else:
            compare_text = str(msg or "").strip()

    except Exception as e:
        print("[Cosmetic-Compare] Error:", repr(e))
        raise HTTPException(500, "Error generando la comparativa con IA.")

    if not compare_text:
        raise HTTPException(500, "La IA no devolvió una comparativa válida.")

    return {
        "pre_image_id": int(pre_image_id),
        "post_image_id": int(post_image_id),
        "compare_text": compare_text,
        "disclaimer": "Comparativa descriptiva. No diagnóstico.",
    }
