# guardia_router.py — De Guardia (CARTELERA COMPARTIDA)
# ✅ Público/privado por caso:
# - visibility: "public" o "private"
# - GET /guard/cases devuelve: (public) + (propios)
# - close/reopen SOLO autor (owner)
# - favoritos por usuario (para casos visibles)
# - adjuntos Modo B siguen funcionando (pero SOLO puedes adjuntar cosas de tus pacientes)

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text, or_
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal

from database import get_db
from auth import get_current_user
from models import GuardCase, GuardMessage, GuardFavorite, DoctorProfile, Analytic, Imaging, Patient

from moderation_utils import quick_block_reason

import crud
from pydantic import BaseModel, Field

router = APIRouter(prefix="/guard", tags=["guardia"])
GUARDIA_MODERATION_VERSION = "DETERMINISTIC_STRICT_V1"




# ======================
# Diagnóstico moderación
# ======================
@router.get("/moderation/version")
def moderation_version():
    return {"version": GUARDIA_MODERATION_VERSION}

# ======================
# Schemas entrada
# ======================
class AttachmentIn(BaseModel):
    kind: Literal["analytic", "imaging"]
    id: int = Field(..., ge=1)


class GuardCaseCreateIn(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    original: Optional[str] = None

    age_group: Optional[str] = None
    sex: Optional[str] = None
    context: Optional[str] = None

    patient_id: Optional[int] = None
    attachments: Optional[List[AttachmentIn]] = None

    # ✅ NUEVO: visibilidad (por defecto public)
    visibility: Optional[Literal["public", "private"]] = "public"


class GuardMessageCreateIn(BaseModel):
    content: str
    attachments: Optional[List[AttachmentIn]] = None


# ======================
# Helpers
# ======================
def _get_guard_alias(db: Session, user_id: int) -> str:
    dp = db.query(DoctorProfile).filter(DoctorProfile.user_id == user_id).first()
    alias = (dp.guard_alias if dp and dp.guard_alias else None)
    return alias or "anónimo"


def _now():
    return datetime.utcnow()


def _extract_case_text(payload: GuardCaseCreateIn) -> str:
    txt = (payload.content or "").strip()
    if not txt:
        txt = (payload.original or "").strip()
    return txt


def _attachments_to_list(payload_list: Optional[List[AttachmentIn]]) -> List[Dict[str, Any]]:
    if not payload_list:
        return []
    out = []
    for a in payload_list:
        if not a:
            continue
        out.append({"kind": a.kind, "id": int(a.id)})
    return out


def _validate_attachments_belong_to_user(
    db: Session,
    current_user_id: int,
    attachments: List[Dict[str, Any]],
):
    if not attachments:
        return

    if len(attachments) > 8:
        raise HTTPException(400, "Demasiados adjuntos (máximo 8 por mensaje).")

    analytic_ids = [a["id"] for a in attachments if a["kind"] == "analytic"]
    imaging_ids = [a["id"] for a in attachments if a["kind"] == "imaging"]

    if analytic_ids:
        rows = (
            db.query(Analytic.id)
            .join(Patient, Patient.id == Analytic.patient_id)
            .filter(Analytic.id.in_(analytic_ids), Patient.doctor_id == current_user_id)
            .all()
        )
        allowed = {r[0] for r in rows}
        for aid in analytic_ids:
            if aid not in allowed:
                raise HTTPException(404, f"Analítica no encontrada o no autorizada (id={aid}).")

    if imaging_ids:
        rows = (
            db.query(Imaging.id)
            .join(Patient, Patient.id == Imaging.patient_id)
            .filter(Imaging.id.in_(imaging_ids), Patient.doctor_id == current_user_id)
            .all()
        )
        allowed = {r[0] for r in rows}
        for iid in imaging_ids:
            if iid not in allowed:
                raise HTTPException(404, f"Imagen no encontrada o no autorizada (id={iid}).")


def _save_message_attachments(db: Session, message_id: int, attachments: List[Dict[str, Any]]):
    if not attachments:
        return
    for a in attachments:
        db.execute(
            sql_text(
                """
                INSERT INTO guard_message_attachments (message_id, kind, ref_id)
                VALUES (:mid, :kind, :rid)
                """
            ),
            {"mid": message_id, "kind": a["kind"], "rid": a["id"]},
        )


def _load_attachments_for_message_ids(
    db: Session,
    message_ids: List[int],
    current_user_id: int,
) -> Dict[int, List[Dict[str, Any]]]:
    if not message_ids:
        return {}

    rows = db.execute(
        sql_text(
            """
            SELECT message_id, kind, ref_id
            FROM guard_message_attachments
            WHERE message_id = ANY(:ids)
            """
        ),
        {"ids": message_ids},
    ).fetchall()

    if not rows:
        return {}

    refs_by_kind = {"analytic": set(), "imaging": set()}
    by_msg: Dict[int, List[Dict[str, Any]]] = {}
    for r in rows:
        mid = int(r[0])
        kind = str(r[1])
        rid = int(r[2])
        by_msg.setdefault(mid, []).append({"kind": kind, "id": rid})
        if kind in refs_by_kind:
            refs_by_kind[kind].add(rid)

    analytics_map: Dict[int, Dict[str, Any]] = {}
    imaging_map: Dict[int, Dict[str, Any]] = {}

    if refs_by_kind["analytic"]:
        arows = (
            db.query(Analytic.id, Analytic.exam_date, Analytic.summary)
            .join(Patient, Patient.id == Analytic.patient_id)
            .filter(Analytic.id.in_(list(refs_by_kind["analytic"])), Patient.doctor_id == current_user_id)
            .all()
        )
        for (aid, exam_date, summary) in arows:
            analytics_map[int(aid)] = {
                "id": int(aid),
                "exam_date": exam_date.isoformat() if exam_date else None,
                "summary": (summary or "").strip(),
            }

    if refs_by_kind["imaging"]:
        irows = (
            db.query(Imaging.id, Imaging.type, Imaging.exam_date, Imaging.summary, Imaging.file_path)
            .join(Patient, Patient.id == Imaging.patient_id)
            .filter(Imaging.id.in_(list(refs_by_kind["imaging"])), Patient.doctor_id == current_user_id)
            .all()
        )
        for (iid, itype, exam_date, summary, file_path) in irows:
            imaging_map[int(iid)] = {
                "id": int(iid),
                "type": (itype or "").strip(),
                "exam_date": exam_date.isoformat() if exam_date else None,
                "summary": (summary or "").strip(),
                "file_path": file_path,
            }

    enriched: Dict[int, List[Dict[str, Any]]] = {}
    for mid, items in by_msg.items():
        out = []
        for a in items:
            kind = a["kind"]
            rid = a["id"]
            if kind == "analytic":
                data = analytics_map.get(rid)
                if data:
                    out.append({"kind": "analytic", **data})
            elif kind == "imaging":
                data = imaging_map.get(rid)
                if data:
                    out.append({"kind": "imaging", **data})
        if out:
            enriched[mid] = out

    return enriched


def _is_favorite(db: Session, user_id: int, case_id: int) -> bool:
    return (
        db.query(GuardFavorite)
        .filter(GuardFavorite.user_id == user_id, GuardFavorite.case_id == case_id)
        .first()
        is not None
    )


def _get_visible_case_or_404(db: Session, case_id: int, current_user_id: int) -> GuardCase:
    c = db.query(GuardCase).filter(GuardCase.id == case_id).first()
    if not c:
        raise HTTPException(404, "Not Found")

    # visible si es tuyo o es público
    vis = getattr(c, "visibility", "public") or "public"
    if c.user_id != current_user_id and vis != "public":
        raise HTTPException(404, "Not Found")
    return c


def _require_owner(db: Session, case_id: int, current_user_id: int) -> GuardCase:
    c = db.query(GuardCase).filter(GuardCase.id == case_id).first()
    if not c:
        raise HTTPException(404, "Not Found")
    if c.user_id != current_user_id:
        raise HTTPException(403, "Solo el autor puede realizar esta acción.")
    return c


# ======================
# OPTIONS adjuntos por paciente (solo para tus pacientes)
# ======================
@router.get("/attachments/options")
def guard_attachment_options(
    patient_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado o no pertenece al usuario.")

    analytics = crud.get_analytics_for_patient(db, patient_id=patient_id)
    imaging = crud.get_imaging_for_patient(db, patient_id=patient_id)

    return {
        "patient_id": patient_id,
        "analytics": [
            {"id": a.id, "exam_date": a.exam_date.isoformat() if a.exam_date else None, "summary": (a.summary or "")}
            for a in (analytics or [])
        ],
        "imaging": [
            {"id": i.id, "type": i.type, "exam_date": i.exam_date.isoformat() if i.exam_date else None, "summary": (i.summary or ""), "file_path": i.file_path}
            for i in (imaging or [])
        ],
    }


# ======================
# GET /guard/cases — cartelera compartida
# Devuelve: casos públicos + tus casos privados
# ======================
@router.get("/cases")
def list_cases(
    status: Optional[str] = Query("open"),
    favorites_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # visibles: public OR owner
    q = db.query(GuardCase).filter(
        or_(
            GuardCase.user_id == current_user.id,
            getattr(GuardCase, "visibility") == "public",
        )
    )

    if status and status != "all":
        q = q.filter(GuardCase.status == status)

    if favorites_only:
        q = q.join(GuardFavorite, GuardFavorite.case_id == GuardCase.id).filter(
            GuardFavorite.user_id == current_user.id
        )

    cases = q.order_by(GuardCase.last_activity_at.desc()).all()

    items = []
    for c in cases:
        # autor: alias del primer mensaje si existe; si no, alias del owner
        first_msg = (
            db.query(GuardMessage)
            .filter(GuardMessage.case_id == c.id)
            .order_by(GuardMessage.id.asc())
            .first()
        )
        author_alias = first_msg.author_alias if first_msg else _get_guard_alias(db, c.user_id)

        msg_count = db.query(GuardMessage).filter(GuardMessage.case_id == c.id).count()

        items.append(
            {
                "id": c.id,
                "title": c.title or "Consulta clínica sin título",
                "anonymized_summary": c.anonymized_summary or "",
                "author_alias": author_alias or "anónimo",
                "status": c.status or "open",
                "message_count": msg_count,
                "last_activity_at": c.last_activity_at,
                "age_group": c.age_group,
                "sex": c.sex,
                "context": c.context,
                "is_favorite": _is_favorite(db, current_user.id, c.id),
                "visibility": getattr(c, "visibility", "public") or "public",
                "is_owner": (c.user_id == current_user.id),
            }
        )

    return {"items": items}


# ======================
# Mensajes — visible si public o owner
# ======================
@router.get("/cases/{case_id}/messages")
def list_messages(
    case_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    c = _get_visible_case_or_404(db, case_id, current_user.id)

    msgs = (
        db.query(GuardMessage)
        .filter(GuardMessage.case_id == case_id)
        .order_by(GuardMessage.id.asc())
        .all()
    )

    # adjuntos: solo enriquecemos si pertenecen al usuario (por privacidad/pacientes)
    msg_ids = [m.id for m in msgs]
    att_map = _load_attachments_for_message_ids(db, msg_ids, current_user.id)

    return {
        "items": [
            {
                "id": m.id,
                "author_alias": m.author_alias or "anónimo",
                "clean_content": m.clean_content or "",
                "moderation_status": m.moderation_status or "ok",
                "created_at": m.created_at,
                "attachments": att_map.get(m.id, []),
            }
            for m in msgs
        ],
        "case": {
            "id": c.id,
            "visibility": getattr(c, "visibility", "public") or "public",
            "is_owner": (c.user_id == current_user.id),
        }
    }


# ======================
# Crear caso — por defecto public
# ======================
@router.post("/cases")
def create_case(
    payload: GuardCaseCreateIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    alias = _get_guard_alias(db, current_user.id)
    content = _extract_case_text(payload)
    if not content:
        raise HTTPException(400, "Contenido vacío")

    blocked, reason = quick_block_reason(content)
    if blocked:
        raise HTTPException(400, f"De Guardia es un espacio clínico profesional. {reason}")

    patient_ref_id = None
    if payload.patient_id:
        patient = crud.get_patient_by_id(db, int(payload.patient_id), current_user.id)
        if not patient:
            raise HTTPException(404, "Paciente no encontrado o no pertenece al usuario.")
        patient_ref_id = int(payload.patient_id)

    attachments = _attachments_to_list(payload.attachments)
    _validate_attachments_belong_to_user(db, current_user.id, attachments)

    visibility = payload.visibility or "public"
    if visibility not in ["public", "private"]:
        visibility = "public"

    case = GuardCase(
        user_id=current_user.id,
        title=(payload.title or "").strip() or "Consulta clínica sin título",
        anonymized_summary=content,
        status="open",
        patient_ref_id=patient_ref_id,
        age_group=payload.age_group,
        sex=payload.sex,
        context=payload.context,
        created_at=_now(),
        last_activity_at=_now(),
    )
    # si el modelo tiene la columna visibility (la añadiremos en migración)
    if hasattr(case, "visibility"):
        setattr(case, "visibility", visibility)

    db.add(case)
    db.commit()
    db.refresh(case)

    msg = GuardMessage(
        case_id=case.id,
        user_id=current_user.id,
        author_alias=alias,
        raw_content=content,
        clean_content=content,
        moderation_status="ok",
        created_at=_now(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    _save_message_attachments(db, msg.id, attachments)
    db.commit()

    return {"id": case.id}


# ======================
# Añadir mensaje — visible si public o owner
# ======================
@router.post("/cases/{case_id}/messages")
def add_message(
    case_id: int,
    payload: GuardMessageCreateIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    c = _get_visible_case_or_404(db, case_id, current_user.id)

    alias = _get_guard_alias(db, current_user.id)
    text = (payload.content or "").strip()
    if not text:
        raise HTTPException(400, "Contenido vacío")

    blocked, reason = quick_block_reason(text)
    if blocked:
        raise HTTPException(400, f"De Guardia es un espacio clínico profesional. {reason}")

    attachments = _attachments_to_list(payload.attachments)
    # solo puedes adjuntar cosas de tus pacientes
    _validate_attachments_belong_to_user(db, current_user.id, attachments)

    msg = GuardMessage(
        case_id=case_id,
        user_id=current_user.id,
        author_alias=alias,
        raw_content=text,
        clean_content=text,
        moderation_status="ok",
        created_at=_now(),
    )
    db.add(msg)

    c.last_activity_at = _now()
    db.add(c)

    db.commit()
    db.refresh(msg)

    _save_message_attachments(db, msg.id, attachments)
    db.commit()

    att_map = _load_attachments_for_message_ids(db, [msg.id], current_user.id)

    return {
        "id": msg.id,
        "author_alias": msg.author_alias,
        "clean_content": msg.clean_content,
        "moderation_status": msg.moderation_status,
        "created_at": msg.created_at,
        "attachments": att_map.get(msg.id, []),
    }


# ======================
# ⭐ Favoritos — para cualquier caso visible
# ======================
@router.post("/cases/{case_id}/favorite")
def favorite_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _get_visible_case_or_404(db, case_id, current_user.id)

    if _is_favorite(db, current_user.id, case_id):
        return {"ok": True}

    fav = GuardFavorite(user_id=current_user.id, case_id=case_id, created_at=_now())
    db.add(fav)
    db.commit()
    return {"ok": True}


@router.delete("/cases/{case_id}/favorite")
def unfavorite_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _get_visible_case_or_404(db, case_id, current_user.id)

    fav = (
        db.query(GuardFavorite)
        .filter(GuardFavorite.user_id == current_user.id, GuardFavorite.case_id == case_id)
        .first()
    )
    if fav:
        db.delete(fav)
        db.commit()
    return {"ok": True}


# ======================
# ✅ Resuelta / Reabrir — SOLO autor
# ======================
@router.post("/cases/{case_id}/close")
def close_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    c = _require_owner(db, case_id, current_user.id)
    c.status = "closed"
    c.last_activity_at = _now()
    db.add(c)
    db.commit()
    return {"ok": True, "status": "closed"}


@router.post("/cases/{case_id}/reopen")
def reopen_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    c = _require_owner(db, case_id, current_user.id)
    c.status = "open"
    c.last_activity_at = _now()
    db.add(c)
    db.commit()
    return {"ok": True, "status": "open"}
