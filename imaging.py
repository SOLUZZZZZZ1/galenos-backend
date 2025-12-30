from typing import Optional, List, Dict, Any
from datetime import datetime
import os
import base64
import hashlib
import json
import io
from PIL import Image

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from openai import OpenAI

from auth import get_current_user
from database import get_db
import crud
import storage_b2
from utils_pdf import convert_pdf_to_images
from utils_imagen import analyze_medical_image
from prompts_imagen import SYSTEM_PROMPT_IMAGEN
from utils_msk_geometry import analyze_msk_geometry, SYSTEM_PROMPT_MSK_GEOMETRY

router = APIRouter(prefix="/imaging", tags=["Imaging"])


def _get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(500, "OPENAI_API_KEY no está configurada.")
    return OpenAI(api_key=api_key)


def _prepare_single_image_b64(file: UploadFile, content: bytes) -> str:
    ct = (file.content_type or "").lower()
    name = (file.filename or "").lower()

    if "pdf" in ct or name.endswith(".pdf"):
        imgs = convert_pdf_to_images(content, max_pages=10, dpi=200)
        if not imgs:
            raise HTTPException(400, "No se han podido extraer imágenes del PDF.")
        return imgs[0]

    if any(name.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff"]):
        return base64.b64encode(content).decode("utf-8")

    if name.endswith(".webp") or "webp" in ct:
        try:
            img = Image.open(io.BytesIO(content)).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as e:
            raise HTTPException(400, f"No se pudo convertir WEBP a PNG: {e}")

    imgs = convert_pdf_to_images(content, max_pages=5, dpi=200)
    if imgs:
        return imgs[0]

    raise HTTPException(400, "Formato no soportado para imagen médica.")


def _parse_exam_date(exam_date: Optional[str]):
    if not exam_date:
        return None
    try:
        return datetime.strptime(exam_date, "%Y-%m-%d").date()
    except:
        return None



# =============================
# UI FAMILY (clasificación ligera para overlays)
# =============================
def _classify_ui_family_from_image(client: OpenAI, *, image_b64: str) -> dict:
    """Clasificador visual ligero para UX (overlays). NO diagnóstico."""
    try:
        model = os.getenv("GALENOS_UI_FAMILY_MODEL") or "gpt-4o-mini"
        prompt = (
            "Clasifica esta imagen médica en una de estas familias para UX:\n"
            "MSK (musculoesquelética), VASCULAR (eco-doppler vasos), CARDIAC (eco corazón), "
            "ABDOMEN (eco abdomen/órganos), LUNG (eco pulmón/pleura), OTHER.\n"
            "No diagnostiques. Si no estás razonablemente seguro, usa OTHER.\n"
            "Responde SOLO JSON: {\"family\":\"MSK|VASCULAR|CARDIAC|ABDOMEN|LUNG|OTHER\",\"confidence\":0-1}."
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Eres un clasificador de familia de imagen para UX. No diagnóstico."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ]},
            ],
        )
        raw = resp.choices[0].message.content
        raw_str = raw if isinstance(raw, str) else json.dumps(raw)
        data = json.loads(raw_str)
        fam = str(data.get("family", "OTHER")).upper().strip()
        conf = float(data.get("confidence", 0) or 0)
        if fam not in ["MSK","VASCULAR","CARDIAC","ABDOMEN","LUNG","OTHER"]:
            fam = "OTHER"
        conf = 0.0 if conf < 0 else (1.0 if conf > 1 else conf)
        return {"family": fam, "confidence": conf}
    except Exception as e:
        print("[UI-FAMILY] Error:", repr(e))
        return {"family": "OTHER", "confidence": 0.0}


# =============================
# STORAGE (Backblaze B2)
# =============================
def _ext_from_filename(name: str) -> str:
    name = (name or "").lower().strip()
    if "." in name:
        return name.rsplit(".", 1)[-1]
    return "bin"

def _b2_upload_original_and_preview(*, user_id: int, kind: str, record_id: int, original_filename: str, original_bytes: bytes, preview_b64: str, preview_ext: str = "png"):
    import base64
    # Original
    orig_ext = _ext_from_filename(original_filename)
    orig_name = f"original.{orig_ext}"
    orig = storage_b2.upload_bytes(
        user_id=user_id,
        category=kind,
        object_id=record_id,
        filename=orig_name,
        data=original_bytes,
    )

    # Preview
    try:
        preview_bytes = base64.b64decode(preview_b64)
    except Exception:
        preview_bytes = b""

    prev_name = f"preview.{preview_ext}"
    prev = storage_b2.upload_bytes(
        user_id=user_id,
        category=kind,
        object_id=record_id,
        filename=prev_name,
        data=preview_bytes if preview_bytes else original_bytes,
    )

    return {
        "original_key": orig["file_key"],
        "preview_key": prev["file_key"],
        "size_bytes": orig["size_bytes"],
        "sha256": orig["sha256"],
        "mime_type": orig["mime_type"],
    }


def _file_path_for_front(db_value: str, *, user_id: int | None = None, record_id: int | None = None, kind: str = "imaging") -> str:
    """
    Convierte el valor guardado en BD (file_path) a una URL usable por frontend.

    - Caso normal: db_value es una key completa de B2 (prod/users/...).
    - Caso legacy: db_value es un nombre simple como "preview.jpg".
      Si tenemos user_id + record_id, intentamos reconstruir la key.
    """
    if not db_value:
        return None
    if isinstance(db_value, str) and db_value.startswith("data:"):
        return db_value
    if isinstance(db_value, str) and (db_value.startswith("http://") or db_value.startswith("https://")):
        return db_value

    val = str(db_value).strip()

    # Legacy: solo filename (sin /)
    if "/" not in val and user_id and record_id:
        candidate = f"prod/users/{int(user_id)}/{kind}/{int(record_id)}/{val}"
        try:
            return storage_b2.generate_presigned_url(file_key=candidate, expires_seconds=3600)
        except Exception:
            # Si no existe, devolvemos None para que el frontend no intente abrir "preview.jpg"
            return None

    try:
        return storage_b2.generate_presigned_url(file_key=val, expires_seconds=3600)
    except Exception:
        return None


def _build_duplicate_response(existing, *, user_id: int | None = None):
    diff_text = ""
    try:
        val = json.loads(existing.differential) if existing.differential else []
        if isinstance(val, list):
            diff_text = "; ".join([str(v).strip() for v in val if str(v).strip()])
        else:
            diff_text = str(val).strip()
    except:
        diff_text = existing.differential or ""

    patterns_list = []
    try:
        for p in getattr(existing, "patterns", []) or []:
            if getattr(p, "pattern_text", None):
                patterns_list.append({"pattern_text": p.pattern_text})
    except:
        pass

    return {
        "id": existing.id,
        "type": existing.type,
        "summary": existing.summary,
        "differential": diff_text,
        "created_at": existing.created_at,
        "exam_date": existing.exam_date,
        "patterns": patterns_list,
        "file_path": _file_path_for_front(existing.file_path, user_id=user_id, record_id=existing.id, kind="imaging"),
        "duplicate": True,
        "ui_family": "OTHER",
        "ui_confidence": 0.0,
    }


@router.post("/upload")
async def upload_imaging(
    patient_id: int = Form(...),
    img_type: str = Form("imagen"),
    context: Optional[str] = Form(None),
    exam_date: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado.")

    # ✅ Cuota de almacenamiento (bloqueo duro >11 GB)
    if crud.is_storage_quota_exceeded(db, current_user.id):
        raise HTTPException(status_code=402, detail="STORAGE_QUOTA_EXCEEDED")

    content = await file.read()
    if not content:
        raise HTTPException(400, "El fichero está vacío.")

    file_hash = hashlib.sha256(content).hexdigest()

    existing = crud.get_imaging_by_hash(db, patient.id, file_hash)
    if existing:
        return _build_duplicate_response(existing, user_id=current_user.id)

    img_b64 = _prepare_single_image_b64(file, content)
    client = _get_openai_client()
    model = os.getenv("GALENOS_VISION_MODEL", "gpt-4o")

    summary, diff_list, patterns = analyze_medical_image(
        client=client,
        image_b64=img_b64,
        model=model,
        system_prompt=SYSTEM_PROMPT_IMAGEN,
        extra_context=context,
    )

    ui = _classify_ui_family_from_image(client, image_b64=img_b64)
    ui_family = ui.get("family", "OTHER")
    ui_confidence = ui.get("confidence", 0.0)

    normalized_type = (img_type or "imagen").strip().upper()
    exam_date_value = _parse_exam_date(exam_date)

    file_path = None

    imaging = crud.create_imaging(
        db=db,
        patient_id=patient.id,
        img_type=normalized_type,
        summary=summary,
        differential=diff_list or [],
        file_path=file_path,
        file_hash=file_hash,
        exam_date=exam_date_value,
    )

    # ✅ Subimos binarios a Backblaze B2 (original + preview) y guardamos SOLO la clave del preview
    try:
        preview_ext = "png"
        lower_name = (file.filename or "").lower()
        if lower_name.endswith(".jpg") or lower_name.endswith(".jpeg"):
            preview_ext = "jpg"
        elif lower_name.endswith(".png"):
            preview_ext = "png"
        elif lower_name.endswith(".webp"):
            preview_ext = "png"  # webp convertido a png

        up = _b2_upload_original_and_preview(
            user_id=current_user.id,
            kind="imaging",
            record_id=imaging.id,
            original_filename=file.filename or "imaging",
            original_bytes=content,
            preview_b64=img_b64,
            preview_ext=preview_ext,
        )
        imaging.file_path = up["preview_key"]
        db.add(imaging)
        db.commit()
        db.refresh(imaging)
    except Exception as e:
        raise HTTPException(500, f"Error subiendo fichero a almacenamiento: {e}")

    crud.add_patterns_to_imaging(db, imaging.id, patterns or [])

    return {
        "id": imaging.id,
        "type": imaging.type,
        "summary": summary,
        "differential": "; ".join(diff_list) if diff_list else "",
        "created_at": imaging.created_at,
        "exam_date": imaging.exam_date,
        "patterns": [{"pattern_text": p} for p in (patterns or [])],
        "file_path": _file_path_for_front(imaging.file_path, user_id=current_user.id, record_id=imaging.id, kind="imaging"),
        "duplicate": False,
        "ui_family": ui_family,
        "ui_confidence": ui_confidence,
    }

@router.get("/by-patient/{patient_id}")
def list_imaging_by_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado o no pertenece al usuario.")

    rows = crud.get_imaging_for_patient(db, patient_id=patient_id)

    results: List[Dict[str, Any]] = []
    for img in rows:
        diff_text = ""
        try:
            val = json.loads(img.differential) if img.differential else []
            if isinstance(val, list):
                diff_text = "; ".join([str(v).strip() for v in val if str(v).strip()])
            else:
                diff_text = str(val).strip()
        except:
            diff_text = img.differential or ""

        patterns_list = []
        try:
            for p in getattr(img, "patterns", []) or []:
                if getattr(p, "pattern_text", None):
                    patterns_list.append({"pattern_text": p.pattern_text})
        except:
            patterns_list = []

        results.append(
            {
                "id": img.id,
                "type": img.type,
                "summary": img.summary,
                "differential": diff_text,
                "created_at": img.created_at,
                "exam_date": img.exam_date,
                "patterns": patterns_list,
                "file_path": _file_path_for_front(img.file_path, user_id=current_user.id, record_id=img.id, kind="imaging"),
            }
        )

    return results



# =============================
# MSK OVERLAY (IA GEOMÉTRICA REAL)
# =============================

def _get_imaging_owned(db: Session, *, imaging_id: int, doctor_id: int):
    q = text(
        """
        SELECT i.id, i.patient_id, i.type, i.summary, i.file_path
        FROM imaging i
        JOIN patients p ON p.id = i.patient_id
        WHERE i.id = :iid AND p.doctor_id = :uid
        """
    )
    r = db.execute(q, {"iid": imaging_id, "uid": doctor_id}).mappings().first()
    return dict(r) if r else None


@router.post("/msk-overlay/{imaging_id}")
def generate_msk_overlay(
    imaging_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
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

    overlay = analyze_msk_geometry(
        client=client,
        image_url=img_url,
        model=model,
        system_prompt=SYSTEM_PROMPT_MSK_GEOMETRY,
    )

    conf = float((overlay or {}).get("confidence", 0.0) or 0.0)

    try:
        db.execute(
            text("UPDATE imaging SET msk_overlay_json = CAST(:j AS jsonb), msk_overlay_confidence = :c WHERE id = :iid"),
            {"j": json.dumps(overlay or {}), "c": conf, "iid": imaging_id},
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error guardando MSK overlay: {e}")

    return {"imaging_id": imaging_id, "msk_overlay": overlay, "saved": True}


@router.put("/msk-overlay/{imaging_id}")
def save_msk_overlay(
    imaging_id: int,
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    row = _get_imaging_owned(db, imaging_id=imaging_id, doctor_id=current_user.id)
    if not row:
        raise HTTPException(404, "Imagen no encontrada o no pertenece al usuario.")

    overlay = payload.get("msk_overlay") if isinstance(payload, dict) else None
    if not isinstance(overlay, dict):
        raise HTTPException(400, 'Payload inválido. Esperado: {"msk_overlay": {...}}')

    conf = float(overlay.get("confidence", 1.0) or 1.0)

    try:
        db.execute(
            text("UPDATE imaging SET msk_overlay_json = CAST(:j AS jsonb), msk_overlay_confidence = :c WHERE id = :iid"),
            {"j": json.dumps(overlay), "c": conf, "iid": imaging_id},
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error guardando MSK overlay: {e}")

    return {"ok": True, "imaging_id": imaging_id}
