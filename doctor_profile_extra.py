# doctor_profile_extra.py — Alias clínico (De guardia) para perfil médico · Galenos.pro
#
# Función:
# - Permitir al médico fijar su alias clínico (guard_alias) una sola vez.
# - Bloquear cambios si el alias ya está fijado.
# - Evitar alias duplicados o confusamente similares (normalización).
#
# Importante:
# - Usa DoctorProfile.guard_alias y DoctorProfile.guard_alias_locked (ya en tu modelo/migración).
# - Se espera que el perfil médico exista antes de fijar alias.

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
import unicodedata

from auth import get_current_user
from database import get_db
from models import DoctorProfile, User

router = APIRouter(prefix="/doctor/profile", tags=["doctor-profile-extra"])


class GuardAliasPayload(BaseModel):
    guard_alias: str


def normalize_alias(alias: str) -> str:
    """
    Normaliza un alias para comparación:
    - minúsculas
    - sin tildes
    - sin espacios, guiones, guiones bajos ni puntos
    """
    a = alias.strip().lower()

    # Quitar tildes
    a = "".join(
        c for c in unicodedata.normalize("NFKD", a)
        if not unicodedata.combining(c)
    )

    for ch in [" ", "_", "-", "."]:
        a = a.replace(ch, "")

    return a


@router.post("/guard-alias")
def set_guard_alias(
    payload: GuardAliasPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fija el alias clínico (De guardia) del médico.
    Reglas:
    - Debe tener perfil médico creado.
    - Alias obligatorio, 3–40 caracteres.
    - No puede ser igual ni confusamente similar al de otro médico.
    - Si guard_alias_locked == 1 → no se puede cambiar.
    """
    alias = (payload.guard_alias or "").strip()
    if not alias:
        raise HTTPException(status_code=400, detail="El alias clínico no puede estar vacío.")
    if len(alias) < 3 or len(alias) > 40:
        raise HTTPException(
            status_code=400,
            detail="El alias clínico debe tener entre 3 y 40 caracteres."
        )

    # Buscar perfil
    profile: Optional[DoctorProfile] = (
        db.query(DoctorProfile)
        .filter(DoctorProfile.user_id == current_user.id)
        .first()
    )
    if not profile:
        raise HTTPException(
            status_code=400,
            detail="Primero completa tu perfil médico antes de configurar el alias clínico.",
        )

    # Si ya está bloqueado (alias fijado previamente), no permitimos cambios
    if getattr(profile, "guard_alias_locked", 0):
        raise HTTPException(
            status_code=400,
            detail="Tu alias clínico ya está fijado y no puede modificarse.",
        )

    # Comprobar colisiones con otros alias (igual o confusamente similar)
    new_norm = normalize_alias(alias)

    existing_profiles = (
        db.query(DoctorProfile)
        .filter(DoctorProfile.guard_alias.isnot(None))
        .all()
    )

    for p in existing_profiles:
        if p.user_id == current_user.id:
            continue
        if not p.guard_alias:
            continue
        existing_norm = normalize_alias(p.guard_alias)
        if existing_norm == new_norm:
            # Alias demasiado parecido
            raise HTTPException(
                status_code=400,
                detail=(
                    "Este alias es demasiado parecido al de otro médico ya registrado en Galenos. "
                    "Por seguridad y para evitar confusiones, elige un alias más diferenciado."
                ),
            )

    # Si todo OK → fijar alias y bloquearlo
    profile.guard_alias = alias
    # Bloqueamos directamente el alias; cuando más adelante haya verificación, esto seguirá siendo válido.
    setattr(profile, "guard_alias_locked", 1)

    db.add(profile)
    db.commit()
    db.refresh(profile)

    return {
        "status": "ok",
        "guard_alias": profile.guard_alias,
        "message": "Alias clínico fijado correctamente. No podrá modificarse.",
    }
