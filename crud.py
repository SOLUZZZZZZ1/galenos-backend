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

# 🔐 Cifrado AES
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
        notes=None  # notas cifradas se añadirán si existe campo
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)

    # Timeline
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
    p = (
        db.query(Patient)
        .filter(
            Patient.id == patient_id,
            Patient.doctor_id == doctor_id,
        )
        .first()
    )

    # DESCIFRAR notas si existen
    if p and p.notes:
        p.notes = decrypt_text(p.notes)

    return p


def update_patient(db: Session, patient: Patient, data: PatientUpdate):
    """Actualiza datos (cifrando notas)."""
    if data.alias is not None:
        patient.alias = data.alias.strip()
    if data.age is not None:
        patient.age = data.age
    if data.gender is not None:
        patient.gender = data.gender.strip() if data.gender else None
    if data.notes is not None:
        patient.notes = encrypt_text(data.notes.strip()) if data.notes else None

    db.commit()
    db.refresh(patient)
    return patient


# ===============================================
# ANALÍTICAS (CIFRADO summary + differential)
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
        summary=encrypt_text(summary),  # 🔐 cifrado
        differential=encrypt_text(json.dumps(differential)),  # 🔐 cifrado
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
        item_id=analytic.id
    )
    db.add(timeline)
    db.commit()

    return analytic


def add_markers_to_analytic(db: Session, analytic_id: int, markers: list):
    """Marcadores NO SE CIFRAN (para búsquedas/rangos, dashboard y comparación)."""
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
    rows = (
        db.query(Analytic)
        .filter(Analytic.patient_id == patient_id)
        .order_by(Analytic.created_at.desc())
        .all()
    )

    # DESCIFRAR summary + differential
    for a in rows:
        a.summary = decrypt_text(a.summary)
        a.differential = decrypt_text(a.differential)
        try:
            a.differential = json.loads(a.differential) if a.differential else []
        except Exception:
            pass

    return rows


def get_analytic_by_hash(db: Session, patient_id: int, file_hash: str):
    a = (
        db.query(Analytic)
        .filter(
            Analytic.patient_id == patient_id,
            Analytic.file_hash == file_hash,
        )
        .first()
    )

    if a:
        a.summary = decrypt_text(a.summary)
        a.differential = decrypt_text(a.differential)
        try:
            a.differential = json.loads(a.differential) if a.differential else []
        except:
            pass

    return a


# ===============================================
# IMAGING (CIFRADO summary + differential)
# ===============================================
def create_imaging(
    db: Session,
    patient_id: int,
    img_type: str,
    summary: str,
    differential,
    file_path: str | None = None,
    file_hash: str | None = None,
    exam_date: date | No=
