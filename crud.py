from sqlalchemy.orm import Session
import json
from datetime import date

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

# 🔐 Cifrado de texto
from security_crypto import encrypt_text, decrypt_text


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
        doctor_id=doctor_id,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)

    # Timeline: creación de paciente
    timeline = TimelineItem(
        patient_id=patient.id,
        item_type="patient",
        item_id=patient.id,
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
    patient = (
        db.query(Patient)
        .filter(
            Patient.id == patient_id,
            Patient.doctor_id == doctor_id,
        )
        .first()
    )

    # DESCIFRAR notas si existen
    if patient and patient.notes:
        patient.notes = decrypt_text(patient.notes)

    return patient


def update_patient(db: Session, patient: Patient, data: PatientUpdate):
    """Actualiza datos básicos del paciente (alias, edad, sexo, notas)."""
    if data.alias is not None:
        patient.alias = data.alias.strip()
    if data.age is not None:
        patient.age = data.age
    if data.gender is not None:
        patient.gender = data.gender.strip() if data.gender else None
    if data.notes is not None:
        notes_clean = data.notes.strip() if data.notes else None
        patient.notes = encrypt_text(notes_clean) if notes_clean else None

    db.commit()
    db.refresh(patient)
    return patient


# ===============================================
# ANALÍTICAS (DE MOMENTO SIN CIFRAR, PARA NO ROMPER UI)
# ===============================================
def create_analytic(
    db: Session,
    patient_id: int,
    summary: str,
    differential,
    file_path: str | None = None,
    file_hash: str | None = None,
    exam_date: date | None = None,
):
    analytic = Analytic(
        patient_id=patient_id,
        summary=summary,
        differential=json.dumps(differential),
        file_path=file_path,
        file_hash=file_hash,
        exam_date=exam_date,
    )
    db.add(analytic)
    db.commit()
    db.refresh(analytic)

    # Timeline
    timeline = TimelineItem(
        patient_id=patient_id,
        item_type="analytic",
        item_id=analytic.id,
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
# IMAGING (TAC / RM / RX) — TAMPOCO CIFRAMOS AÚN
# ===============================================
def create_imaging(
    db: Session,
    patient_id: int,
    img_type: str,
    summary: str,
    differential,
    file_path: str | None = None,
    file_hash: str | None = None,
    exam_date: date | None = None,
):
    imaging = Imaging(
        patient_id=patient_id,
        type=img_type,
        summary=summary,
        differential=json.dumps(differential),
        file_path=file_path,
        file_hash=file_hash,
        exam_date=exam_date,
    )
    db.add(imaging)
    db.commit()
    db.refresh(imaging)

    # Timeline
    timeline = TimelineItem(
        patient_id=patient_id,
        item_type="imaging",
        item_id=imaging.id,
    )
    db.add(timeline)
    db.commit()

    return imaging


def add_patterns_to_imaging(db: Session, imaging_id: int, patterns: list):
    for p in patterns:
        obj = ImagingPattern(
            imaging_id=imaging_id,
            pattern_text=p if isinstance(p, str) else str(p),
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
# CLINICAL NOTES (CIFRADAS)
# ===============================================
def create_clinical_note(
    db: Session,
    patient_id: int,
    doctor_id: int,
    data: ClinicalNoteCreate,
):
    """Crea nota clínica cifrando título y contenido."""
    title_clean = data.title.strip() if data.title else None
    content_clean = data.content.strip() if data.content else None

    note = ClinicalNote(
        patient_id=patient_id,
        doctor_id=doctor_id,
        title=encrypt_text(title_clean) if title_clean else None,
        content=encrypt_text(content_clean) if content_clean else None,
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    # 🔓 DESCIFRAR SOLO PARA LA RESPUESTA (en BD sigue cifrado)
    note.title = decrypt_text(note.title)
    note.content = decrypt_text(note.content)

    # Timeline
    timeline = TimelineItem(
        patient_id=patient_id,
        item_type="note",
        item_id=note.id,
    )
    db.add(timeline)
    db.commit()

    return note



def get_notes_for_patient(db: Session, patient_id: int):
    notes = (
        db.query(ClinicalNote)
        .filter(ClinicalNote.patient_id == patient_id)
        .order_by(ClinicalNote.created_at.desc())
        .all()
    )

    # DESCIFRAR antes de devolver
    for note in notes:
        note.title = decrypt_text(note.title)
        note.content = decrypt_text(note.content)

    return notes


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
