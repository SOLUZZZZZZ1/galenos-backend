# guardia_router.py — Módulo "De guardia / Cartelera clínica" · Galenos.pro
#
# Funcionalidad:
# - Crear consultas de guardia (casos clínicos)
# - Usar opcionalmente el historial del paciente (última analítica / imagen)
# - Listar casos de guardia (cartelera)
# - Ver detalle de un caso
# - Hilo de mensajes entre médicos
# - Favoritos
# - Resumen simple del debate
#
# Requiere:
# - Tablas: guard_cases, guard_messages, guard_favorites
# - Modelos: GuardCase, GuardMessage, GuardFavorite, Analytic, Imaging
# - auth.get_current_user
# - security_crypto.encrypt_text

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user
from models import GuardCase, GuardMessage, GuardFavorite, User, Analytic, Imaging
from security_crypto import encrypt_text

router = APIRouter(prefix="/guard", tags=["guardia"])


# =========================================================
# MODELOS Pydantic (solo para este router)
# =========================================================

class GuardCaseCreate(BaseModel):
    """
    Datos que envía el frontend al crear una consulta de guardia.
    patient_id es opcional; si viene, se usará el historial de ese paciente.
    """
    patient_id: Optional[int] = None
    title: str
    age_group: Optional[str] = None
    sex: Optional[str] = None
    context: Optional[str] = None
    main_symptoms: str
    key_findings: Optional[str] = None
    clinical_question: str
    free_text: Optional[str] = None


class GuardCasePreviewResponse(BaseModel):
    anonymized_summary: str


class GuardCaseListItem(BaseModel):
    id: int
    title: Optional[str]
    anonymized_summary: Optional[str]
    author_alias: str
    status: str
    message_count: int
    last_activity_at: datetime
    is_favorite: bool
    age_group: Optional[str] = None
    sex: Optional[str] = None
    context: Optional[str] = None


class GuardCaseListResponse(BaseModel):
    items: List[GuardCaseListItem]


class GuardCaseDetail(BaseModel):
    id: int
    title: Optional[str]
    anonymized_summary: Optional[str]
    author_alias: str
    status: str
    age_group: Optional[str] = None
    sex: Optional[str] = None
    context: Optional[str] = None
    created_at: datetime
    last_activity_at: datetime


class GuardMessageCreate(BaseModel):
    content: str


class GuardMessageOut(BaseModel):
    id: int
    author_alias: str
    clean_content: str
    moderation_status: str
    created_at: datetime


class GuardMessagesListResponse(BaseModel):
    items: List[GuardMessageOut]


class IASummaryResponse(BaseModel):
    summary: str


# =========================================================
# Moderación y anonimización básica (sin IA externa)
# =========================================================

def moderate_and_anonimize(text: str) -> tuple[str, str, str]:
    """
    Moderación prudente:
    - Oculta posibles emails
    - Oculta posibles teléfonos
    - Enmascara insultos habituales (lenguaje ofensivo)
    (Se puede extender con DNIs, direcciones, etc.)

    Devuelve:
    - clean_text
    - moderation_status: "ok" | "auto_cleaned" | "moderated"
    - reason: explicación corta (opcional)
    """
    if not text:
        return "", "ok", ""

    clean = text
    status = "ok"
    reason = ""

    import re

    # Emails
    email_pattern = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b")
    if email_pattern.search(clean):
        clean = email_pattern.sub("***", clean)
        status = "auto_cleaned"
        reason = "Se han eliminado posibles emails."

    # Teléfonos tipo 600123456, 600 123 456, etc.
    phone_pattern = re.compile(r"\b\d{3}[\s\-]?\d{2,3}[\s\-]?\d{2,3}\b")
    if phone_pattern.search(clean):
        clean = phone_pattern.sub("***", clean)
        if status == "ok":
            status = "auto_cleaned"
            reason = "Se han eliminado posibles teléfonos."
        else:
            reason = (reason + " Se han eliminado posibles teléfonos.").strip()

    # Lista básica de insultos a enmascarar (se puede ampliar)
    forbidden_words = [
        "idiota",
        "subnormal",
        "gilipollas",
        "imbécil",
        "capullo",
        "cabrón",
        "mierda",
    ]

    insults_found = False

    def mask_match(match: re.Match) -> str:
        original = match.group(0)
        return "*" * len(original)

    for bad in forbidden_words:
        pattern = re.compile(rf"\b{re.escape(bad)}\b", re.IGNORECASE)
        if pattern.search(clean):
            insults_found = True
            clean = pattern.sub(mask_match, clean)

    if insults_found:
        # Marcamos como moderado y añadimos motivo
        if status == "ok":
            status = "moderated"
            reason = "Lenguaje ofensivo enmascarado automáticamente."
        else:
            status = "moderated"
            extra = " Se ha enmascarado lenguaje ofensivo."
            reason = (reason + extra).strip()

    return clean, status, reason


def build_case_summary(payload: GuardCaseCreate) -> str:
    """
    Construye el bloque clínico de la consulta a partir del formulario.
    Esto es lo que tú escribes: síntomas, hallazgos, pregunta, texto libre.
    """
    parts: list[str] = []

    # Cabecera: edad, sexo, contexto
    header = []
    if payload.age_group:
        header.append(payload.age_group)
    if payload.sex:
        header.append(payload.sex)
    if payload.context:
        header.append(payload.context)
    if header:
        parts.append(" · ".join(header))

    if payload.main_symptoms:
        parts.append(f"SÍNTOMAS PRINCIPALES:\n{payload.main_symptoms.strip()}")

    if payload.key_findings:
        parts.append(f"HALLAZGOS RELEVANTES:\n{payload.key_findings.strip()}")

    if payload.clinical_question:
        parts.append(f"PREGUNTA CLÍNICA:\n{payload.clinical_question.strip()}")

    if payload.free_text:
        parts.append(f"TEXTO LIBRE:\n{payload.free_text.strip()}")

    return "\n\n".join(parts).strip()


def build_support_from_patient(db: Session, patient_id: int) -> str:
    """
    Toma la última analítica y la última imagen de un paciente,
    y construye un bloque de texto clínico de apoyo para De guardia.

    Usa:
    - Analytic.summary
    - Imaging.summary
    """
    parts: list[str] = []

    # Última analítica (por exam_date o, si no, por created_at)
    last_analytic = (
        db.query(Analytic)
        .filter(Analytic.patient_id == patient_id)
        .order_by(
            Analytic.exam_date.desc().nullslast()
            if hasattr(Analytic.exam_date, "desc")
            else Analytic.created_at.desc()
        )
        .first()
    )
    if last_analytic and last_analytic.summary:
        parts.append(
            "DATOS DE APOYO (Analítica más reciente):\n"
            + last_analytic.summary.strip()
        )

    # Última imagen
    last_imaging = (
        db.query(Imaging)
        .filter(Imaging.patient_id == patient_id)
        .order_by(
            Imaging.exam_date.desc().nullslast()
            if hasattr(Imaging.exam_date, "desc")
            else Imaging.created_at.desc()
        )
        .first()
    )
    if last_imaging and last_imaging.summary:
        parts.append(
            "DATOS DE APOYO (Imagen médica más reciente):\n"
            + last_imaging.summary.strip()
        )

    return "\n\n".join(parts).strip()


# =========================================================
# PREVIEW — /guard/cases/preview
# =========================================================

@router.post("/cases/preview", response_model=GuardCasePreviewResponse)
def preview_guard_case(
    payload: GuardCaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Construye el texto completo:
    - resumen clínico del formulario
    - + datos de apoyo (analítica/imaging) si viene patient_id

    Lo pasa por moderación/anonimización
    y devuelve solo la versión segura (anonymized_summary).
    """
    base = build_case_summary(payload)
    original = base

    # Si hay patient_id, añadimos el bloque de apoyo del historial
    if payload.patient_id:
        support = build_support_from_patient(db, payload.patient_id)
        if support:
            original = (base + "\n\n" + support).strip()

    clean, status, _reason = moderate_and_anonimize(original)
    anonymized = clean if clean else original

    return GuardCasePreviewResponse(anonymized_summary=anonymized)


# =========================================================
# CREAR CASO — /guard/cases (POST)
# =========================================================

@router.post("/cases", response_model=GuardCaseListItem)
def create_guard_case(
    payload: GuardCaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Crea:
    - un GuardCase
    - y su primer GuardMessage (el caso inicial como mensaje)
    """
    base = build_case_summary(payload)
    original = base

    if payload.patient_id:
        support = build_support_from_patient(db, payload.patient_id)
        if support:
            original = (base + "\n\n" + support).strip()

    clean, status, _reason = moderate_and_anonimize(original)
    anonymized = clean if clean else original

    # Alias de guardia obligatorio
    author_alias = (
        current_user.doctor_profile.guard_alias
        if current_user.doctor_profile else None
    )
    if not author_alias:
        raise HTTPException(
            status_code=400,
            detail="No tienes alias de guardia configurado. Configúralo antes de publicar.",
        )

    now = datetime.utcnow()

    # Crear caso
    guard_case = GuardCase(
        user_id=current_user.id,
        title=payload.title.strip(),
        age_group=payload.age_group or None,
        sex=payload.sex or None,
        context=payload.context or None,
        anonymized_summary=anonymized,
        status="open",
        patient_ref_id=payload.patient_id,  # vínculo interno con el paciente (no visible en la cartelera)
        created_at=now,
        last_activity_at=now,
    )
    db.add(guard_case)
    db.commit()
    db.refresh(guard_case)

    # Crear primer mensaje (caso inicial)
    encrypted_raw = encrypt_text(original) if original else None
    msg = GuardMessage(
        case_id=guard_case.id,
        user_id=current_user.id,
        author_alias=author_alias,
        raw_content=encrypted_raw,
        clean_content=anonymized,
        moderation_status=status,
        moderation_reason=None,
        created_at=now,
    )
    db.add(msg)
    db.commit()

    # Recontar mensajes
    message_count = (
        db.query(GuardMessage)
        .filter(GuardMessage.case_id == guard_case.id)
        .count()
    )

    return GuardCaseListItem(
        id=guard_case.id,
        title=guard_case.title,
        anonymized_summary=guard_case.anonymized_summary,
        author_alias=author_alias,
        status=guard_case.status or "open",
        message_count=message_count,
        last_activity_at=guard_case.last_activity_at,
        is_favorite=False,
        age_group=guard_case.age_group,
        sex=guard_case.sex,
        context=guard_case.context,
    )


# =========================================================
# LISTAR CASOS — /guard/cases (GET)
# =========================================================

@router.get("/cases", response_model=GuardCaseListResponse)
def list_guard_cases(
    status: str = Query("open", description="open | closed | all"),
    favorites: bool = Query(False),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(GuardCase).filter()

    if status == "open":
        q = q.filter(GuardCase.status == "open")
    elif status == "closed":
        q = q.filter(GuardCase.status == "closed")

    if search:
        like = f"%{search}%"
        q = q.filter(
            GuardCase.title.ilike(like) |
            GuardCase.anonymized_summary.ilike(like)
        )

    if favorites:
        q = (
            q.join(GuardFavorite, GuardFavorite.case_id == GuardCase.id)
            .filter(GuardFavorite.user_id == current_user.id)
        )

    q = q.order_by(GuardCase.last_activity_at.desc())

    cases = q.all()

    # IDs de favoritos del usuario
    fav_ids = {
        f.case_id
        for f in db.query(GuardFavorite)
        .filter(GuardFavorite.user_id == current_user.id)
        .all()
    }

    items: List[GuardCaseListItem] = []
    for c in cases:
        message_count = (
            db.query(GuardMessage)
            .filter(GuardMessage.case_id == c.id)
            .count()
        )

        author_alias = c.messages[0].author_alias if c.messages else "guardia"

        items.append(
            GuardCaseListItem(
                id=c.id,
                title=c.title,
                anonymized_summary=c.anonymized_summary,
                author_alias=author_alias,
                status=c.status or "open",
                message_count=message_count,
                last_activity_at=c.last_activity_at or c.created_at,
                is_favorite=(c.id in fav_ids),
                age_group=c.age_group,
                sex=c.sex,
                context=c.context,
            )
        )

    return GuardCaseListResponse(items=items)


# =========================================================
# DETALLE DE CASO — /guard/cases/{case_id}
# =========================================================

@router.get("/cases/{case_id}", response_model=GuardCaseDetail)
def get_guard_case(
    case_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = db.query(GuardCase).filter(GuardCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Consulta de guardia no encontrada.")

    author_alias = case.messages[0].author_alias if case.messages else "guardia"

    return GuardCaseDetail(
        id=case.id,
        title=case.title,
        anonymized_summary=case.anonymized_summary,
        author_alias=author_alias,
        status=case.status or "open",
        age_group=case.age_group,
        sex=case.sex,
        context=case.context,
        created_at=case.created_at,
        last_activity_at=case.last_activity_at or case.created_at,
    )


# =========================================================
# LISTAR MENSAJES — /guard/cases/{case_id}/messages (GET)
# =========================================================

@router.get("/cases/{case_id}/messages", response_model=GuardMessagesListResponse)
def list_guard_messages(
    case_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = db.query(GuardCase).filter(GuardCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Consulta de guardia no encontrada.")

    msgs = (
        db.query(GuardMessage)
        .filter(GuardMessage.case_id == case_id)
        .order_by(GuardMessage.created_at.asc())
        .all()
    )

    items = [
        GuardMessageOut(
            id=m.id,
            author_alias=m.author_alias or "guardia",
            clean_content=m.clean_content or "",
            moderation_status=m.moderation_status or "ok",
            created_at=m.created_at,
        )
        for m in msgs
    ]

    return GuardMessagesListResponse(items=items)


# =========================================================
# AÑADIR MENSAJE — /guard/cases/{case_id}/messages (POST)
# =========================================================

@router.post("/cases/{case_id}/messages", response_model=GuardMessageOut)
def add_guard_message(
    case_id: int,
    payload: GuardMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = db.query(GuardCase).filter(GuardCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Consulta de guardia no encontrada.")

    text = payload.content.strip()
    if not text:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío.")

    clean, status, reason = moderate_and_anonimize(text)
    final_text = clean or text

    author_alias = (
        current_user.doctor_profile.guard_alias
        if current_user.doctor_profile else None
    )
    if not author_alias:
        raise HTTPException(
            status_code=400,
            detail="No tienes alias de guardia configurado. Configúralo antes de responder.",
        )

    now = datetime.utcnow()
    encrypted_raw = encrypt_text(text)

    msg = GuardMessage(
        case_id=case.id,
        user_id=current_user.id,
        author_alias=author_alias,
        raw_content=encrypted_raw,
        clean_content=final_text,
        moderation_status=status,
        moderation_reason=reason or None,
        created_at=now,
    )

    db.add(msg)
    case.last_activity_at = now
    db.add(case)

    db.commit()
    db.refresh(msg)

    return GuardMessageOut(
        id=msg.id,
        author_alias=msg.author_alias or "guardia",
        clean_content=msg.clean_content or "",
        moderation_status=msg.moderation_status or "ok",
        created_at=msg.created_at,
    )


# =========================================================
# FAVORITOS
# =========================================================

@router.post("/cases/{case_id}/favorite")
def mark_favorite_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = db.query(GuardCase).filter(GuardCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Consulta de guardia no encontrada.")

    existing = (
        db.query(GuardFavorite)
        .filter(
            GuardFavorite.user_id == current_user.id,
            GuardFavorite.case_id == case_id,
        )
        .first()
    )
    if existing:
        return {"status": "ok", "is_favorite": True}

    fav = GuardFavorite(
        user_id=current_user.id,
        case_id=case_id,
        created_at=datetime.utcnow(),
    )
    db.add(fav)
    db.commit()

    return {"status": "ok", "is_favorite": True}


@router.delete("/cases/{case_id}/favorite")
def unmark_favorite_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fav = (
        db.query(GuardFavorite)
        .filter(
            GuardFavorite.user_id == current_user.id,
            GuardFavorite.case_id == case_id,
        )
        .first()
    )
    if fav:
        db.delete(fav)
        db.commit()

    return {"status": "ok", "is_favorite": False}


# =========================================================
# RESUMEN IA (simple) — /guard/cases/{case_id}/summary-ia
# =========================================================

@router.get("/cases/{case_id}/summary-ia", response_model=IASummaryResponse)
def summarize_case_debate(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Resumen simple del debate:
    - No llama a ningún servicio externo
    - Nunca debe dar error de conexión
    """
    case = db.query(GuardCase).filter(GuardCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Consulta de guardia no encontrada.")

    msgs = (
        db.query(GuardMessage)
        .filter(GuardMessage.case_id == case_id)
        .order_by(GuardMessage.created_at.asc())
        .all()
    )

    if not msgs:
        return IASummaryResponse(
            summary="Todavía no hay suficientes mensajes para generar un resumen."
        )

    fragments = []
    max_msgs = 6
    for m in msgs[:max_msgs]:
        alias = m.author_alias or "guardia"
        text = (m.clean_content or "").strip()
        if text:
            fragments.append(f"- {alias}: {text}")

    summary_text = "Resumen simple del debate entre médicos:\n\n" + "\n".join(fragments)

    return IASummaryResponse(summary=summary_text)
