from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Text, Date
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


# =========================
# USER
# =========================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
    is_active = Column(Integer, default=1)

    is_pro = Column(Integer, default=0)
    stripe_customer_id = Column(String)
    stripe_subscription_id = Column(String)
    trial_end = Column(DateTime)

    patients = relationship("Patient", back_populates="doctor")
    cancellations = relationship("CancellationReason", back_populates="user")

    doctor_profile = relationship(
        "DoctorProfile",
        back_populates="user",
        uselist=False,
    )

    invitations_created = relationship(
        "Invitation",
        back_populates="created_by",
        foreign_keys="Invitation.created_by_id",
    )


# =========================
# PERFIL MÉDICO
# =========================
class DoctorProfile(Base):
    __tablename__ = "doctor_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True)

    first_name = Column(String(100))
    last_name = Column(String(100))
    specialty = Column(String(120))
    colegiado_number = Column(String(50))
    phone = Column(String(30))
    center = Column(String(150))
    city = Column(String(120))
    bio = Column(Text)

    guard_alias = Column(String(80))
    guard_alias_locked = Column(Integer, default=0)

    user = relationship("User", back_populates="doctor_profile")


# =========================
# PATIENT
# =========================
class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True)
    doctor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    alias = Column(String, nullable=False)
    age = Column(Integer)
    gender = Column(String)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    patient_number = Column(Integer)

    doctor = relationship("User", back_populates="patients")
    analytics = relationship("Analytic", back_populates="patient", cascade="all, delete")
    imaging = relationship("Imaging", back_populates="patient", cascade="all, delete")
    notes_rel = relationship("ClinicalNote", back_populates="patient", cascade="all, delete")
    timeline_items = relationship("TimelineItem", back_populates="patient", cascade="all, delete")


# =========================
# ANALYTICS
# =========================
class Analytic(Base):
    __tablename__ = "analytics"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    summary = Column(Text)
    differential = Column(Text)
    file_path = Column(String)
    file_hash = Column(String)
    exam_date = Column(Date)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="analytics")
    markers = relationship("AnalyticMarker", back_populates="analytic", cascade="all, delete")


class AnalyticMarker(Base):
    __tablename__ = "analytic_markers"

    id = Column(Integer, primary_key=True)
    analytic_id = Column(Integer, ForeignKey("analytics.id"), nullable=False)
    name = Column(String, nullable=False)
    value = Column(Float)
    unit = Column(String)
    ref_min = Column(Float)
    ref_max = Column(Float)

    analytic = relationship("Analytic", back_populates="markers")


# =========================
# IMAGING
# =========================
class Imaging(Base):
    __tablename__ = "imaging"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    type = Column(String)
    summary = Column(Text)
    differential = Column(Text)
    file_path = Column(String)
    file_hash = Column(String)
    exam_date = Column(Date)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="imaging")
    patterns = relationship("ImagingPattern", back_populates="imaging", cascade="all, delete")


class ImagingPattern(Base):
    __tablename__ = "imaging_patterns"

    id = Column(Integer, primary_key=True)
    imaging_id = Column(Integer, ForeignKey("imaging.id"), nullable=False)
    pattern_text = Column(Text, nullable=False)

    imaging = relationship("Imaging", back_populates="patterns")


# =========================
# CLINICAL NOTES
# =========================
class ClinicalNote(Base):
    __tablename__ = "clinical_notes"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="notes_rel")


# =========================
# TIMELINE
# =========================
class TimelineItem(Base):
    __tablename__ = "timeline_items"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    item_type = Column(String, nullable=False)
    item_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="timeline_items")


# =========================
# MÓDULO DE GUARDIA
# =========================
class GuardCase(Base):
    __tablename__ = "guard_cases"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    title = Column(Text)
    age_group = Column(Text)
    sex = Column(Text)
    context = Column(Text)

    anonymized_summary = Column(Text)
    status = Column(Text, default="open")

    patient_ref_id = Column(Integer)

    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity_at = Column(DateTime, default=datetime.utcnow)

    # ✅ NUEVO — CLAVE PARA CARTELERA COMPARTIDA
    visibility = Column(Text, default="public")

    messages = relationship("GuardMessage", back_populates="case", cascade="all, delete")
    favorites = relationship("GuardFavorite", back_populates="case", cascade="all, delete")


class GuardMessage(Base):
    __tablename__ = "guard_messages"

    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("guard_cases.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    author_alias = Column(Text)
    raw_content = Column(Text)
    clean_content = Column(Text)

    moderation_status = Column(Text)
    moderation_reason = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    case = relationship("GuardCase", back_populates="messages")


class GuardFavorite(Base):
    __tablename__ = "guard_favorites"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("guard_cases.id"), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    case = relationship("GuardCase", back_populates="favorites")


# =========================
# ACTUALIDAD MÉDICA
# =========================
class MedicalNews(Base):
    __tablename__ = "medical_news"

    id = Column(Integer, primary_key=True)
    title = Column(Text, nullable=False)
    summary = Column(Text)
    source_name = Column(String)
    source_url = Column(String, nullable=False)
    published_at = Column(DateTime)
    specialty_tags = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
