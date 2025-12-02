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

    # Campos PRO / Stripe
    is_pro = Column(Integer, default=0)  # 0 = no PRO, 1 = PRO
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    trial_end = Column(DateTime, nullable=True)

    patients = relationship("Patient", back_populates="doctor")


# ===============================================
# PATIENT
# ===============================================
class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    alias = Column(String, nullable=False)
    age = Column(Integer, nullable=True)
    gender = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    doctor = relationship("User", back_populates="patients")
    analytics = relationship("Analytic", back_populates="patient", cascade="all, delete")
    imaging = relationship("Imaging", back_populates="patient", cascade="all, delete")
    notes_rel = relationship("ClinicalNote", back_populates="patient", cascade="all, delete")
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


class ImagingPattern(Base):
    __tablename__ = "imaging_patterns"

    id = Column(Integer, primary_key=True, index=True)
    imaging_id = Column(Integer, ForeignKey("imaging.id"), nullable=False)
    pattern_text = Column(Text, nullable=False)

    imaging = relationship("Imaging", back_populates="patterns")


# ===============================================
# CLINICAL NOTES
# ===============================================
class ClinicalNote(Base):
    __tablename__ = "clinical_notes"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="notes_rel")


# ===============================================
# TIMELINE
# ===============================================
class TimelineItem(Base):
    __tablename__ = "timeline_items"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    item_type = Column(String, nullable=False)  # 'patient' | 'analytic' | 'imaging' | 'note'
    item_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="timeline_items")
