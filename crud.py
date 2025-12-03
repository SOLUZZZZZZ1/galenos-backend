from sqlalchemy.orm import Session
import json

from models import (
    User,
    Patient,
    Analytic,
    AnalyticMarker,
    Imaging,
    ImagingPattern,
    ClinicalNote,
    TimelineItem,
)
from schemas import PatientCreate, PatientUpdate, ClinicalNoteCreate


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


def update_patient(db: Session, patient: Patient, data: PatientUpdate):
    """Actualiza datos básicos del paciente (alias, edad, sexo, notas)."""
    if data.alias is not None:
        patient.alias = data.alias.strip()
    if data.age is not None:
        patient.age = data.age
    if data.gender is not None:
        patient.gender = data.gender.strip() if data.gender else None
    if data.notes is not None:
        patient.notes = data.notes.strip() if data.notes else None

    db.commit()
    db.refresh(patient)
    return patient


# ===============================================
# ANALÍTICAS
# ===============================================
def create_analytic(
    db: Session,
    patient_id: int,
    summary: str,
    differential,
    file_path: str | None = None,
    file_hash: str | None = None,
):
    analytic = Analytic(
        patient_id=patient_id,
        summary=summary,
        differential=json.dumps(differential),
        file_path=file_path,
        file_hash=file_hash,
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


def get_analytic_by_hash(db: Session, patient_id: int, file_hash: str):
    return (
        db.query(Analytic)
        .filter(
            Analytic.patient_id == patient_id,
            Analytic.file_hash == file_hash,
        )
        .first()
    )


# ===============================================
# IMAGING (TAC / RM / RX)
# ===============================================
def create_imaging(
    db: Session,
    patient_id: int,
    img_type: str,
    summary: str,
    differential,
    file_path: str | None = None,
    file_hash: str | None = None,
):
    imaging = Imaging(
        patient_id=patient_id,
        type=img_type,
        summary=summary,
        differential=json.dumps(differential),
        file_path=file_path,
        file_hash=file_hash,
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
            pattern_text=p if isinstance(p, str) else str(p)
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


def get_imaging_by_hash(db: Session, patient_id: int, file_hash: str):
    return (
        db.query(Imaging)
        .filter(
            Imaging.patient_id == patient_id,
            Imaging.file_hash == file_hash,
        )
        .first()
    )


# ===============================================
# CLINICAL NOTES
# ===============================================
def create_clinical_note(db: Session, patient_id: int, doctor_id: int, data: ClinicalNoteCreate):
    note = ClinicalNote(
        patient_id=patient_id,
        doctor_id=doctor_id,
        title=data.title.strip(),
        content=data.content.strip()
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
