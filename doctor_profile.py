from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user
import models, crud
from schemas import (
    DoctorProfileCreate,
    DoctorProfileUpdate,
    DoctorProfileReturn,
)

router = APIRouter(prefix="/doctor/profile", tags=["doctor_profile"])


@router.get("/me", response_model=DoctorProfileReturn)
def get_my_profile(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    profile = crud.get_doctor_profile_by_user(db, current_user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil médico no encontrado.")

    return {
        "id": profile.id,
        "user_id": current_user.id,
        "email": current_user.email,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "specialty": profile.specialty,
        "colegiado_number": profile.colegiado_number,
        "phone": profile.phone,
        "center": profile.center,
        "city": profile.city,
        "bio": profile.bio,
    }


@router.post("/me", response_model=DoctorProfileReturn)
def create_my_profile(
    data: DoctorProfileCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    existing = crud.get_doctor_profile_by_user(db, current_user.id)
    if existing:
        raise HTTPException(
            status_code=400,
            detail="El perfil ya existe. Usa PUT para actualizarlo.",
        )

    profile = crud.create_doctor_profile(db, current_user, data)

    return {
        "id": profile.id,
        "user_id": current_user.id,
        "email": current_user.email,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "specialty": profile.specialty,
        "colegiado_number": profile.colegiado_number,
        "phone": profile.phone,
        "center": profile.center,
        "city": profile.city,
        "bio": profile.bio,
    }


@router.put("/me", response_model=DoctorProfileReturn)
def update_my_profile(
    data: DoctorProfileUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    profile = crud.get_doctor_profile_by_user(db, current_user.id)
    if not profile:
        profile = crud.create_doctor_profile(db, current_user, data)
    else:
        profile = crud.update_doctor_profile(db, profile, data)

    return {
        "id": profile.id,
        "user_id": current_user.id,
        "email": current_user.email,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "specialty": profile.specialty,
        "colegiado_number": profile.colegiado_number,
        "phone": profile.phone,
        "center": profile.center,
        "city": profile.city,
        "bio": profile.bio,
    }
