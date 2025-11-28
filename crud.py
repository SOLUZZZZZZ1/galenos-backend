# crud.py — Lógica de base de datos (CRUD) para Galenos.pro

from sqlalchemy.orm import Session
from datetime import datetime
import json

from models import (
    User,
    Patient,
    Analytic,
    AnalyticMarker,
    Imaging,
    ImagingPattern,
    ClinicalNote,
    TimelineItem
)
from schemas import PatientCreate, ClinicalNoteCreate


# ===============================================
# USER / MÉDICO
# ===============================================
def get_user_by_id(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()


# ===============================================
# PACIENTES
# ===============================================
def create_patient(db: Session, doctor_id: int, data: PatientCreate):
    patient = Patient(
        alias=data.alias,
        doctor_id=doctor_id
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)

    # Timeline: creación de paciente
    timeline = TimelineItem(
        patient_id=patient.id,
        item_type="patient",
        item_id=patient.id
    )
    db.add(timeline)
    db.commit()

    return patient


def get_patients_for_doctor(db: Session, doctor_id: int):
    return db.query(Patient).filter(Patient.doctor_id == doctor_id).order_by(Patient.created_at.desc()).all()


def get_patient_by_id(db: Session, patient_id: int, doctor_id:_
