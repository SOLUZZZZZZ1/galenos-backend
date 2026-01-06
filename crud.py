# crud.py — Lógica de base de datos para Galenos.pro
from sqlalchemy.orm import Session
import json
from datetime import date, datetime

from sqlalchemy import func

from models import (
    User,
    Patient,
    Analytic,
    AnalyticMarker,
    Imaging,
    ImagingPattern,
    ClinicalNote,
    TimelineItem,
    DoctorProfile,
    PatientReviewState,
)

from schemas import (
    PatientCreate,
    PatientUpdate,
    ClinicalNoteCreate,
    DoctorProfileCreate,
    DoctorProfileUpdate,
)

# 🔐 Cifrado de texto
from security_crypto import encrypt_text, decrypt_text

# ✅ Storage (B2) for hard delete cleanup
import storage_b2


# ===============================================
# USER / MÉDICO
# ===============================================
def get_user_by_id(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()


# ===============================================
# PACIENTES
# ===============================================
def create_patient(db: Session, doctor_id: int, data: PatientCreate):
    """
    Crea un paciente nuevo para un médico:
    - Alias
    - doctor_id
    - Asigna patient_number secuencial por médico (1,2,3…)
    - Añade evento de alta en el timeline
    """

    # Buscar el último número de paciente para este médico
    last = (
        db.query(Patient)
        .filter(Patient.doctor_id == doctor_id)
        .order_by(Patient.patient_number.desc().nullslast())
        .first()
    )

    next_number = 1
    if last and last.patient_number:
        next_number = last.patient_number + 1

    patient = Patient(
        alias=data.alias,
        doctor_id=doctor_id,
        patient_number=next_number,
    )
    # archived default should be False at DB level; keep safe in case model has it.
    if hasattr(patient, "archived"):
        setattr(patient, "archived", False)

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


def get_patients_for_doctor(db: Session, doctor_id: int, *, include_archived: bool = False, archived_only: bool = False):
    q = db.query(Patient).filter(Patient.doctor_id == doctor_id)

    # Compatibilidad: si no existe columna archived, devuelve como siempre
    if hasattr(Patient, "archived"):
        if archived_only:
            q = q.filter(Patient.archived == True)   # noqa: E712
        elif not include_archived:
            q = q.filter((Patient.archived == False) | (Patient.archived.is_(None)))  # noqa: E712

    return q.order_by(Patient.created_at.desc()).all()


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


# ✅ Archivar / Restaurar (soft delete)
def archive_patient(db: Session, patient: Patient):
    if not hasattr(patient, "archived"):
        # Si aún no existe la columna, no rompemos nada:
        return patient
    patient.archived = True
    db.commit()
    db.refresh(patient)
    return patient


def unarchive_patient(db: Session, patient: Patient):
    if not hasattr(patient, "archived"):
        return patient
    patient.archived = False
    db.commit()
    db.refresh(patient)
    return patient


# ===============================================
# ESTADO DE REVISIÓN (Última revisión por médico y paciente)
# ===============================================
def get_review_state(db: Session, doctor_id: int, patient_id: int):
    return (
        db.query(PatientReviewState)
        .filter(
            PatientReviewState.doctor_id == doctor_id,
            PatientReviewState.patient_id == patient_id,
        )
        .first()
    )


def upsert_review_state(db: Session, doctor_id: int, patient_id: int, last_reviewed_analytic_id: int | None):
    state = get_review_state(db, doctor_id, patient_id)
    if state:
        state.last_reviewed_at = datetime.utcnow()
        state.last_reviewed_analytic_id = last_reviewed_analytic_id
    else:
        state = PatientReviewState(
            doctor_id=doctor_id,
            patient_id=patient_id,
            last_reviewed_at=datetime.utcnow(),
            last_reviewed_analytic_id=last_reviewed_analytic_id,
        )
        db.add(state)
    db.commit()
    db.refresh(state)
    return state


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
    """
    Guarda marcadores de una analítica, limpiando valores no numéricos
    para que no reviente la BD cuando la IA devuelve cosas tipo "Negatiu", "Positiu++", etc.
    """

    def to_float_or_none(val):
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    for m in markers:
        name = m.get("name")
        if not name:
            continue

        value = to_float_or_none(m.get("value"))
        ref_min = to_float_or_none(m.get("ref_min"))
        ref_max = to_float_or_none(m.get("ref_max"))
        unit = m.get("unit")

        marker = AnalyticMarker(
            analytic_id=analytic_id,
            name=name,
            value=value,
            unit=unit,
            ref_min=ref_min,
            ref_max=ref_max,
        )
        db.add(marker)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise e


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
    timeline_item_type: str = "imaging",
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

    if not timeline_item_type:
        timeline_item_type = "imaging"

    # Timeline
    timeline = TimelineItem(
        patient_id=patient_id,
        item_type=timeline_item_type,
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
# NOTAS CLÍNICAS
# ===============================================
def create_clinical_note(
    db: Session,
    patient_id: int,
    doctor_id: int,
    note_data: ClinicalNoteCreate,
):
    """
    Crea una nota clínica cifrando título y contenido.
    """

    title_clean = note_data.title.strip()
    content_clean = note_data.content.strip()

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


# ===============================================
# DOCTOR PROFILE
# ===============================================
def get_doctor_profile_by_user(db: Session, user_id: int):
    return (
        db.query(DoctorProfile)
        .filter(DoctorProfile.user_id == user_id)
        .first()
    )


def create_doctor_profile(db: Session, user: User, data: DoctorProfileCreate):
    profile = DoctorProfile(
        user_id=user.id,
        first_name=data.first_name,
        last_name=data.last_name,
        specialty=data.specialty,
        colegiado_number=data.colegiado_number,
        phone=data.phone,
        center=data.center,
        city=data.city,
        bio=data.bio,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def update_doctor_profile(db: Session, profile: DoctorProfile, data: DoctorProfileUpdate):
    for field, value in data.dict(exclude_unset=True).items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile


# ===============================================
# STORAGE / CUOTA DE ALMACENAMIENTO
# ===============================================
MAX_QUOTA_BYTES = 10 * 1024 * 1024 * 1024   # 10 GB
HARD_LIMIT_BYTES = 11 * 1024 * 1024 * 1024  # margen técnico


def get_used_bytes_for_user(db: Session, user_id: int) -> int:
    """
    Devuelve el total de bytes usados por un médico sumando:
    - analytics.size_bytes
    - imaging.size_bytes
    """
    total_analytics = (
        db.query(func.coalesce(func.sum(Analytic.size_bytes), 0))
        .join(Patient, Analytic.patient_id == Patient.id)
        .filter(Patient.doctor_id == user_id)
        .scalar()
    )

    total_imaging = (
        db.query(func.coalesce(func.sum(Imaging.size_bytes), 0))
        .join(Patient, Imaging.patient_id == Patient.id)
        .filter(Patient.doctor_id == user_id)
        .scalar()
    )

    return int(total_analytics or 0) + int(total_imaging or 0)


def is_storage_quota_exceeded(db: Session, user_id: int) -> bool:
    """True si supera el límite duro (>11 GB)."""
    used = get_used_bytes_for_user(db, user_id)
    return used > HARD_LIMIT_BYTES


def get_storage_quota_status(db: Session, user_id: int) -> dict:
    """Estado de cuota para avisos UX."""
    used = get_used_bytes_for_user(db, user_id)
    return {
        "used_bytes": used,
        "limit_bytes": MAX_QUOTA_BYTES,
        "near_limit": used >= 9 * 1024 * 1024 * 1024,
        "at_limit": used >= MAX_QUOTA_BYTES,
        "hard_exceeded": used > HARD_LIMIT_BYTES,
    }


# ===============================================
# ROI (Región clínica analizada) — Imaging
# ===============================================
def set_imaging_roi(db: Session, imaging_id: int, roi: dict | None, version: str = "ROI_V1"):
    """Guarda ROI en Imaging para limpiar overlays y análisis futuros."""
    imaging = db.query(Imaging).filter(Imaging.id == imaging_id).first()
    if not imaging:
        return None
    imaging.roi_json = roi
    imaging.roi_version = version
    db.commit()
    db.refresh(imaging)
    return imaging


# ===============================================
# ✅ HARD DELETE (Paciente + historial + B2)
# ===============================================
def delete_patient_permanently(db: Session, patient: Patient, *, doctor_id: int):
    """
    Borrado irreversible:
    - Paciente + historial completo en BD (analytics, markers, imaging, patterns, notes, timeline, review_state)
    - Limpieza de ficheros en Backblaze B2 (por prefijo, original+preview)
    """
    patient_id = int(patient.id)

    # 1) Recolectar IDs antes de borrar (para borrar B2 por prefijo)
    analytic_ids = [int(a.id) for a in db.query(Analytic.id).filter(Analytic.patient_id == patient_id).all()]
    imaging_ids = [int(i.id) for i in db.query(Imaging.id).filter(Imaging.patient_id == patient_id).all()]

    # 2) Borrar B2 (mejor esfuerzo). Si falla B2, NO borramos BD -> evitamos huérfanos “invisibles”
    #    Si prefieres lo contrario, te lo cambio, pero esta es la opción más segura.
    try:
        # Imaging (incluye cosmetic, porque category="imaging" también en cosmetic router)
        for iid in imaging_ids:
            prefix = f"prod/users/{int(doctor_id)}/imaging/{iid}/"
            storage_b2.delete_prefix(prefix)

        # Analytics (si usas category="analytics" o "analytics" en upload)
        # Aunque no tengamos el upload aquí, este prefijo es la convención natural.
        for aid in analytic_ids:
            prefix = f"prod/users/{int(doctor_id)}/analytics/{aid}/"
            storage_b2.delete_prefix(prefix)

    except Exception as e:
        # No tocamos BD si no pudimos limpiar storage de forma consistente
        raise RuntimeError(f"Error limpiando almacenamiento (B2). No se ha borrado en BD. Detalle: {e}")

    # 3) BD: borrar dependencias explícitas (aunque haya cascades, lo dejamos determinista)
    try:
        # Markers
        if analytic_ids:
            db.query(AnalyticMarker).filter(AnalyticMarker.analytic_id.in_(analytic_ids)).delete(synchronize_session=False)

        # Imaging patterns
        if imaging_ids:
            db.query(ImagingPattern).filter(ImagingPattern.imaging_id.in_(imaging_ids)).delete(synchronize_session=False)

        # Timeline
        db.query(TimelineItem).filter(TimelineItem.patient_id == patient_id).delete(synchronize_session=False)

        # Notes
        db.query(ClinicalNote).filter(ClinicalNote.patient_id == patient_id).delete(synchronize_session=False)

        # Review state
        db.query(PatientReviewState).filter(
            PatientReviewState.doctor_id == int(doctor_id),
            PatientReviewState.patient_id == patient_id,
        ).delete(synchronize_session=False)

        # Imaging + Analytics
        db.query(Imaging).filter(Imaging.patient_id == patient_id).delete(synchronize_session=False)
        db.query(Analytic).filter(Analytic.patient_id == patient_id).delete(synchronize_session=False)

        # Patient
        db.query(Patient).filter(Patient.id == patient_id, Patient.doctor_id == int(doctor_id)).delete(synchronize_session=False)

        db.commit()
        return True

    except Exception as e:
        db.rollback()
        raise e
