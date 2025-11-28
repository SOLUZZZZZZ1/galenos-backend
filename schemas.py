# schemas.py — Esquemas Pydantic para Galenos.pro

from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime


# ===============================================
# USER (médico)
# ===============================================
class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str
    name: Optional[str] = None

class UserReturn(UserBase):
    id: int
    name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ===============================================
# LOGIN
# ===============================================
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ===============================================
# PATIENT
# ===============================================
class PatientBase(BaseModel):
    alias: str

class PatientCreate(PatientBase):
    pass

class PatientReturn(PatientBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ===============================================
# ANALYTIC MARKERS
# ===============================================
class MarkerReturn(BaseModel):
    name: str
    value: Optional[float]
    unit: Optional[str]
    ref_min: Optional[float]
    ref_max: Optional[float]

    class Config:
        from_attributes = True


# ===============================================
# ANALYTIC
# ===============================================
class AnalyticReturn(BaseModel):
    id: int
    summary: Optional[str]
    differential: Optional[str]
    created_at: datetime
    markers: List[MarkerReturn]

    class Config:
        from_attributes = True


# ===============================================
# IMAGING
# ===============================================
class ImagingPatternReturn(BaseModel):
    pattern_text: str

    class Config:
        from_attributes = True

class ImagingReturn(BaseModel):
    id: int
    type: Optional
