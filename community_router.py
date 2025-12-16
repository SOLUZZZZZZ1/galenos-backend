# community_router.py — Módulo Comunidad (formativo)
# SAFE: independiente de Guardia y Pacientes
# Endpoints v1: listar, crear caso, ver caso, responder

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import datetime
from typing import Optional

from database import get_db
from auth import get_current_user
from models import CommunityCase, CommunityResponse, DoctorProfile
from pydantic import BaseModel, Field

router = APIRouter(prefix="/community", tags=["community"])


class CommunityCaseCreateIn(BaseModel):
    title: Optional[str] = None
    clinical_context: Optional[str] = None
    question: Optional[str] = None
    visibility: Optional[str] = Field("public", description="public | private")


class CommunityResponseCreateIn(BaseModel):
    content: str


def _now():
    return datetime.utcnow()


def _get_guard_alias(db: Session, user_id: int) -> str:
    dp = db.query(DoctorProfile).filter(DoctorProfile.user_id == user_id).first()
    return (dp.guard_alias if dp and dp.guard_alias else None) or "anónimo"


def _get_visible_case_or_404(db: Session, case_id: int, current_user_id: int) -> CommunityCase:
    c = db.query(CommunityCase).filter(CommunityCase.id == case_id).first()
    if not c:
        raise HTTPException(404, "Not Found")
    if c.user_id != current_user_id and (c.visibility_
