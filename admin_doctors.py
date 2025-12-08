# admin_doctors.py — Gestión básica de médicos para panel admin · Galenos.pro
#
# Función:
# - Listar médicos (usuarios + perfil médico) para el panel admin.
# - Solo accesible para el usuario maestro.
#
# No modifica nada, solo LEE. Es totalmente seguro.

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional

from database import get_db
from auth import get_current_user
from models import User, DoctorProfile

router = APIRouter(prefix="/admin/doctors", tags=["admin-doctors"])

MASTER_EMAIL = "soluzziona@gmail.com"  # mismo criterio que AdminPanel.jsx


class AdminDoctorItem(BaseModel):
    user_id: int
    email: str
    created_at: Optional[str]
    has_profile: bool
    first_name: Optional[str]
    last_name: Optional[str]
    specialty: Optional[str]
    colegiado_number: Optional[str]


class AdminDoctorsList(BaseModel):
    items: List[AdminDoctorItem]


def ensure_master(current_user: User):
    """
    Solo permite acceso al usuario maestro.
    """
    if not current_user or current_user.email != MASTER_EMAIL:
        raise HTTPException(
            status_code=403,
            detail="Solo el usuario maestro puede acceder a esta función.",
        )


@router.get("", response_model=AdminDoctorsList)
def list_doctors(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lista médicos (usuarios de la plataforma) con su perfil médico si existe.
    No modifica nada, solo LEE.
    """
    ensure_master(current_user)

    users = db.query(User).order_by(User.created_at.desc()).all()

    items: list[AdminDoctorItem] = []
    for u in users:
        profile: Optional[DoctorProfile] = u.doctor_profile

        items.append(
            AdminDoctorItem(
                user_id=u.id,
                email=u.email,
                created_at=u.created_at.isoformat() if u.created_at else None,
                has_profile=bool(profile),
                first_name=profile.first_name if profile else None,
                last_name=profile.last_name if profile else None,
                specialty=profile.specialty if profile else None,
                colegiado_number=profile.colegiado_number if profile else None,
            )
        )

    return AdminDoctorsList(items=items)
