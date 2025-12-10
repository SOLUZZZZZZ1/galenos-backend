from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime, date


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


class PatientUpdate(BaseModel):
    alias: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    notes: Optional[str] = None


class PatientReturn(PatientBase):
    id: int
    created_at: datetime
    age: Optional[int] = None
    gender: Optional[str] = None
    notes: Optional[str] = None
    # 👇 NUEVO: número clínico por médico (1,2,3…)
    patient_number: Optional[int] = None

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
    # NUEVOS CAMPOS PARA EL FRONTEND
    range: Optional[str] = None
    status: Optional[str] = None

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
    exam_date: Optional[date] = None
    markers: List[MarkerReturn]
    file_path: Optional[str] = None  # miniatura (data URL PNG) para la analítica

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
    type: Optional[str]
    summary: Optional[str]
    differential: Optional[str]
    created_at: datetime
    exam_date: Optional[date] = None
    patterns: List[ImagingPatternReturn]
    file_path: Optional[str] = None  # miniatura (data URL PNG) para la imagen

    class Config:
        from_attributes = True


# ===============================================
# NOTES (Notas clínicas)
# ===============================================
class ClinicalNoteBase(BaseModel):
    title: str
    content: str


class ClinicalNoteCreate(ClinicalNoteBase):
    pass


class ClinicalNoteReturn(ClinicalNoteBase):
    id: int
    patient_id: int
    doctor_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ===============================================
# TIMELINE
# ===============================================
class TimelineItemReturn(BaseModel):
    id: int
    item_type: str
    item_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ===============================================
# INVITATIONS / ACCESS REQUESTS
# ===============================================
class InvitationReturn(BaseModel):
    invite_url: str


class RegisterWithInviteRequest(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None
    token: str


class AccessRequestCreate(BaseModel):
    name: str
    email: EmailStr
    country: str
    city: str
    speciality: Optional[str] = None
    center: Optional[str] = None
    phone: Optional[str] = None
    how_heard: Optional[str] = None
    message: Optional[str] = None


class AccessRequestReturn(BaseModel):
    id: int
    name: str
    email: EmailStr
    country: str
    city: str
    speciality: Optional[str]
    center: Optional[str]
    phone: Optional[str]
    how_heard: Optional[str]
    message: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ===============================================
# DOCTOR PROFILE (Perfil Médico)
# ===============================================
class DoctorProfileBase(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    specialty: Optional[str] = None
    colegiado_number: Optional[str] = None
    phone: Optional[str] = None
    center: Optional[str] = None
    city: Optional[str] = None
    bio: Optional[str] = None


class DoctorProfileCreate(DoctorProfileBase):
    pass


class DoctorProfileUpdate(DoctorProfileBase):
    pass


class DoctorProfileReturn(DoctorProfileBase):
    id: int
    user_id: int
    email: EmailStr
    # 👇 NUEVOS CAMPOS: alias clínico (De guardia)
    guard_alias: Optional[str] = None
    guard_alias_locked: bool = False

    class Config:
        from_attributes = True


# ===============================================
# MEDICAL NEWS (Actualidad médica)
# ===============================================
class MedicalNewsReturn(BaseModel):
    id: int
    title: str
    summary: Optional[str] = None
    source_name: Optional[str] = None
    source_url: str
    published_at: Optional[datetime] = None
    specialty_tags: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
