from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


# ===============================================
# USER (Médico)
# ===============================================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Integer, default=1)

    patients = relationship("Patient", back_populates="doctor")


# ===============================================
# PATIENT
# ===============================================
class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    alias = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    doctor = relationship("User", back_populates="patients")
    analytics = relationship("Analytic", back_populates="patient", cascade="all, delete")
    imaging = relationship("Imaging", back_populates="patient", cascade="all, delete")
    notes = relationship("ClinicalNote", back_populates="patient", cascade="all, delete")
    timeline_items = relationship("TimelineItem", back_populates="patient", cascade="all, delete")


# ===============================================
# ANALYTIC (Analítica)
# ===============================================
class Analytic(Base):
    __tablename__ = "analytics"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    summary = Column(Text, nullable=True)
    differential = Column(Text, nullable=True)
    file_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="analytics")
    markers = relationship("AnalyticMarker", back_populates="analytic", cascade="all, delete")


# ===============================================
# ANALYTIC MARKERS
# ===============================================
class AnalyticMarker(Base):
    __tablename__ = "analytic_markers"

    id = Column(Integer, primary_key=True, index=True)
    analytic_id = Column(Integer, ForeignKey("analytics.id"), nullable=False)
    name = Column(String, nullable=False)
    value = Column(Float, nullable=True)
    unit = Column(String, nullable=True)
    ref_min = Column(Float, nullable=True)
    ref_max = Column(Float, nullable=True)

    analytic = relationship("Analytic", back_populates="markers")


# ===============================================
# IMAGING (TAC / RM / RX / ECO)
# ===============================================
class Imaging(Base):
    __tablename__ = "imaging"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    type = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    differential = Column(Text, nullable=True)
    file_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="imaging")
    patterns = relationship("ImagingPattern", back_populates="imaging", cascade="all, delete")


# ===============================================
# IMAGING PATTERNS (patrones visuales)
# ===============================================
class ImagingPattern(Base):
    __tablename__ = "imaging_patterns"

    id = Column(Integer, primary_key=True, index=True)
    imaging_id = Column(Integer, ForeignKey("imaging.id"), nullable=False)
    pattern_text = Column(String, nullable=False)

    imaging = relationship("Imaging", back_populates="patterns")


# ===============================================
# NOTES (Notas clínicas)
# ===============================================
class ClinicalNote(Base):
    __tablename__ = "clinical_notes"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="notes")
    doctor = relationship("User")


# ===============================================
# TIMELINE (Historia clínica lineal)
# ===============================================
class TimelineItem(Base):
    __tablename__ = "timeline_items"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    item_type = Column(String, nullable=False)  # "analytic", "imaging", "note"
    item_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="timeline_items")


# ===============================================
# INVITATIONS (Invitaciones para médicos)
# ===============================================
class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)  # Ej: ahora + 30 días
    max_uses = Column(Integer, default=1)
    used_count = Column(Integer, default=0)

    creator = relationship("User")
