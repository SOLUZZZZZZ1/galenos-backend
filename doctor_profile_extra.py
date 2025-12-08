# doctor_profile_extra.py — Alias de guardia para perfil médico

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import DoctorProfile, User

router = APIRouter(prefix="/doctor/profile", tags=["doctor-profile-extra"])


class GuardAliasPayload(BaseModel):
  guard_alias: str


@router.post("/guard-alias")
def set_guard_alias(
  payload: GuardAliasPayload,
  db: Session = Depends(get_db),
  current_user: User = Depends(get_current_user),
):
  alias = (payload.guard_alias or "").strip()
  if not alias:
    raise HTTPException(status_code=400, detail="El alias de guardia no puede estar vacío.")
  if len(alias) < 3 or len(alias) > 40:
    raise HTTPException(status_code=400, detail="El alias debe tener entre 3 y 40 caracteres.")

  # Buscar perfil
  profile = (
    db.query(DoctorProfile)
    .filter(DoctorProfile.user_id == current_user.id)
    .first()
  )
  if not profile:
    raise HTTPException(
      status_code=400,
      detail="Primero completa tu perfil médico antes de configurar el alias de guardia.",
    )

  # Si ya está bloqueado, no permitimos cambios
  if profile.guard_alias_locked:
    raise HTTPException(
      status_code=400,
      detail="Tu alias de guardia ya está fijado y no puede modificarse.",
    )

  # Comprobar que el alias no esté en uso por otro médico
  exists = (
    db.query(DoctorProfile)
    .filter(
      DoctorProfile.guard_alias == alias,
      DoctorProfile.user_id != current_user.id,
    )
    .first()
  )
  if exists:
    raise HTTPException(
      status_code=400,
      detail="Este alias ya está en uso por otro médico. Elige otro.",
    )

  profile.guard_alias = alias
  # NO bloqueamos aquí; se bloqueará cuando envíe su primer mensaje si más adelante lo deseas.
  db.add(profile)
  db.commit()
  db.refresh(profile)

  return {"status": "ok", "guard_alias": profile.guard_alias}
