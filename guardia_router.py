# guardia_router.py — Módulo De guardia / Cartelera clínica · Galenos.pro

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user
from models import GuardCase, GuardMessage, GuardFavorite, User
from security_crypto import encrypt_text

router = APIRouter(prefix="/guard", tags=["guardia"])


# =========================================================
# MODELOS Pydantic (solo para este router)
# =========================================================

class GuardCaseCreate(BaseModel):
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
# Moderación y anonimización rudimentaria
# (sin IA externa, pero preparada para mejorar)
# =========================================================

def moderate_and_anonimize(text: str) -> tuple[str, str, str]:
  """
  Aplica una moderación muy prudente:
  - Tapa posibles teléfonos
  - Tapa posibles emails
  - Deja el resto igual

  Devuelve (clean_text, moderation_status, reason)
  """
  if not text:
    return "", "ok", ""

  clean = text
  status = "ok"
  reason = ""

  # Emails
  import re

  email_pattern = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b")
  if email_pattern.search(clean):
    clean = email_pattern.sub("***", clean)
    status = "auto_cleaned"
    reason = "Se han eliminado posibles emails."

  # Teléfonos tipo 600 123 456, 600123456, etc.
  phone_pattern = re.compile(r"\b\d{3}[\s\-]?\d{2,3}[\s\-]?\d{2,3}\b")
  if phone_pattern.search(clean):
    clean = phone_pattern.sub("***", clean)
    if status == "ok":
      status = "auto_cleaned"
      reason = "Se han eliminado posibles teléfonos."
    else:
      reason = (reason + " Se han eliminado posibles teléfonos.").strip()

  # Podríamos añadir más reglas aquí (DNIs, direcciones, etc.)

  return clean, status, reason


def build_case_summary(payload: GuardCaseCreate) -> str:
  """
  Construye un resumen clínico en texto plano a partir del formulario estructurado.
  Este resumen es el que se anonimiza y guarda en guard_cases.anonymized_summary.
  """
  parts = []

  if payload.age_group or payload.sex or payload.context:
    header = []
    if payload.age_group:
      header.append(payload.age_group)
    if payload.sex:
      header.append(payload.sex)
    if payload.context:
      header.append(payload.context)
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


# =========================================================
# ENDPOINT: PREVIEW (anonimizar antes de publicar)
# =========================================================

@router.post("/cases/preview", response_model=GuardCasePreviewResponse)
def preview_guard_case(
  payload: GuardCaseCreate,
  current_user: User = Depends(get_current_user),
):
  original = build_case_summary(payload)
  clean, status, _reason = moderate_and_anonimize(original)

  # En esta fase nunca bloqueamos, solo limpiamos
  anonymized = clean if clean else original

  return GuardCasePreviewResponse(anonymized_summary=anonymized)


# =========================================================
# ENDPOINT: CREAR CASO (y primer mensaje)
# =========================================================

@router.post("/cases", response_model=GuardCaseListItem)
def create_guard_case(
  payload: GuardCaseCreate,
  db: Session = Depends(get_db),
  current_user: User = Depends(get_current_user),
):
  original = build_case_summary(payload)
  clean, status, _reason = moderate_and_anonimize(original)
  anonymized = clean if clean else original

  author_alias = current_user.doctor_profile.guard_alias if current_user.doctor_profile else None
  if not author_alias:
    raise HTTPException(
      status_code=400,
      detail="No tienes alias de guardia configurado. Configúralo antes de publicar.",
    )

  now = datetime.utcnow()

  # 1) Crear el caso
  guard_case = GuardCase(
    user_id=current_user.id,
    title=payload.title.strip(),
    age_group=payload.age_group or None,
    sex=payload.sex or None,
    context=payload.context or None,
    anonymized_summary=anonymized,
    status="open",
    created_at=now,
    last_activity_at=now,
  )
  db.add(guard_case)
  db.commit()
  db.refresh(guard_case)

  # 2) Crear el primer mensaje (el caso inicial como mensaje del autor)
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
  db.refresh(msg)

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
# ENDPOINT: LISTAR CASOS (cartelera)
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
    q = q.filter(GuardCase.title.ilike(like) | GuardCase.anonymized_summary.ilike(like))

  # Si solo queremos favoritas, cruzamos con guard_favorites
  if favorites:
    q = (
      q.join(GuardFavorite, GuardFavorite.case_id == GuardCase.id)
      .filter(GuardFavorite.user_id == current_user.id)
    )

  q = q.order_by(GuardCase.last_activity_at.desc())

  cases = q.all()

  # Pre-calcular favoritos del usuario
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

    # alias del autor del caso (quien lo creó)
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
# ENDPOINT: DETALLE DE CASO
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
# ENDPOINT: LISTAR MENSAJES
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
# ENDPOINT: AÑADIR MENSAJE AL HILO
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

  # En esta versión NO bloqueamos, solo limpiamos
  final_text = clean or text

  author_alias = current_user.doctor_profile.guard_alias if current_user.doctor_profile else None
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

  # Actualizar last_activity_at del caso
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
# RESUMEN IA DEL DEBATE (versión simple)
# =========================================================

@router.get("/cases/{case_id}/summary-ia", response_model=IASummaryResponse)
def summarize_case_debate(
  case_id: int,
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

  if not msgs:
    return IASummaryResponse(summary="Todavía no hay suficientes mensajes para generar un resumen.")

  # Versión simple: coger las primeras N aportaciones y concatenar
  fragments = []
  max_msgs = 6
  for m in msgs[:max_msgs]:
    alias = m.author_alias or "guardia"
    text = (m.clean_content or "").strip()
    if text:
      fragments.append(f"- {alias}: {text}")

  summary_text = "Resumen simple del debate entre médicos:\n\n" + "\n".join(fragments)

  return IASummaryResponse(summary=summary_text)
