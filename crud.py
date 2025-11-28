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
    return (
        db.query(Patient)
        .filter(Patient.doctor_id == doctor_id)
        .order_by(Patient.created_at.desc())
        .all()
    )


def get_patient_by_id(db: Session, patient_id: int, doctor_id: int):
    return (
        db.query(Patient)
        .filter(
            Patient.id == patient_id,
            Patient.doctor_id == doctor_id,
        )
        .first()
    )


# ===============================================
# ANALÍTICAS
# ===============================================
def create_analytic(db: Session, patient_id: int, summary: str, differential, file_path: str = None):
    analytic = Analytic(
        patient_id=patient_id,
        summary=summary,
        differential=json.dumps(differential),
        file_path=file_path
    )
    db.add(analytic)
    db.commit()
    db.refresh(analytic)

    # Timeline
    timeline = TimelineItem(
        patient_id=patient_id,
        item_type="analytic",
        item_id=analytic.id
    )
    db.add(timeline)
    db.commit()

    return analytic


def add_markers_to_analytic(db: Session, analytic_id: int, markers: list):
    for m in markers:
        marker = AnalyticMarker(
            analytic_id=analytic_id,
            name=m.get("name"),
            value=m.get("value"),
            unit=m.get("unit"),
            ref_min=m.get("ref_min"),
            ref_max=m.get("ref_max"),
        )
        db.add(marker)
    db.commit()


def get_analytics_for_patient(db: Session, patient_id: int):
    return (
        db.query(Analytic)
        .filter(Analytic.patient_id == patient_id)
        .order_by(Analytic.created_at.desc())
        .all()
    )


# ===============================================
# IMAGING (TAC / RM / RX)
# ===============================================
def create_imaging(db: Session, patient_id: int, img_type: str, summary: str, differential, file_path: str = None):
    imaging = Imaging(
        patient_id=patient_id,
        type=img_type,
        summary=summary,
        differential=json.dumps(differential),
        file_path=file_path
    )
    db.add(imaging)
    db.commit()
    db.refresh(imaging)

    # Timeline
    timeline = TimelineItem(
        patient_id=patient_id,
        item_type="imaging",
        item_id=imaging.id
    )
    db.add(timeline)
    db.commit()

    return imaging


def add_patterns_to_imaging(db: Session, imaging_id: int, patterns: list):
    for p in patterns:
        obj = ImagingPattern(
            imaging_id=imaging_id,
            pattern_text=p
        )
        db.add(obj)
    db.commit()


def get_imaging_for_patient(db: Session, patient_id: int):
    return (
        db.query(Imaging)
        .filter(Imaging.patient_id == patient_id)
        .order_by(Imaging.created_at.desc())
        .all()
    )


# ===============================================
# NOTES (Notas clínicas)
# ===============================================
def create_clinical_note(db: Session, patient_id: int, doctor_id: int, data: ClinicalNoteCreate):
    note = ClinicalNote(
        patient_id=patient_id,
        doctor_id=doctor_id,
        title=data.title,
        content=data.content
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    # Timeline
    timeline = TimelineItem(
        patient_id=patient_id,
        item_type="note",
        item_id=note.id
    )
    db.add(timeline)
    db.commit()

    return note


def get_notes_for_patient(db: Session, patient_id: int):
    return (
        db.query(ClinicalNote)
        .filter(ClinicalNote.patient_id == patient_id)
        .order_by(ClinicalNote.created_at.desc())
        .all()
    )


# ===============================================
# TIMELINE
# ===============================================
def get_timeline_for_patient(db: Session, patient_id: int):
    return (
        db.query(TimelineItem)
        .filter(TimelineItem.patient_id == patient_id)
        .order_by(TimelineItem.created_at.desc())
        .all()
    )
