import os
from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text
from database import engine

router = APIRouter(prefix="/admin/migrate-galenos", tags=["admin-migrate-galenos"])

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN") or "GalenosAdminToken@123"

def _auth(x_admin_token: str | None):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "Unauthorized")

# -------------------------
# TABLAS
# -------------------------

SQL_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP NULL,
    is_active INTEGER DEFAULT 1,
    is_pro INTEGER DEFAULT 0,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    trial_end TIMESTAMP
);
"""

# 🔹 PERFIL MÉDICO (NUEVO)
SQL_DOCTOR_PROFILES = """
CREATE TABLE IF NOT EXISTS doctor_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    first_name TEXT,
    last_name TEXT,
    specialty TEXT,
    colegiado_number TEXT,
    phone TEXT,
    center TEXT,
    city TEXT,
    bio TEXT
);
"""

# 🔹 EXTENSIÓN PERFIL: alias de guardia
SQL_DOCTOR_PROFILES_ALTER = """
ALTER TABLE doctor_profiles
    ADD COLUMN IF NOT EXISTS guard_alias TEXT;

ALTER TABLE doctor_profiles
    ADD COLUMN IF NOT EXISTS guard_alias_locked INTEGER DEFAULT 0;
"""

SQL_PATIENTS = """
CREATE TABLE IF NOT EXISTS patients (
    id SERIAL PRIMARY KEY,
    doctor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    age INTEGER,
    gender TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

# 🔹 EXTENSIÓN PACIENTES: numeración por médico (patient_number)
SQL_PATIENTS_ALTER = """
ALTER TABLE patients
    ADD COLUMN IF NOT EXISTS patient_number INTEGER;
"""

# 🔹 RELLENAR patient_number PARA PACIENTES EXISTENTES
SQL_PATIENTS_BACKFILL = """
WITH ordered AS (
    SELECT
        id,
        doctor_id,
        ROW_NUMBER() OVER (
            PARTITION BY doctor_id
            ORDER BY created_at ASC, id ASC
        ) AS rn
    FROM patients
)
UPDATE patients p
SET patient_number = o.rn
FROM ordered o
WHERE p.id = o.id
  AND (p.patient_number IS NULL OR p.patient_number = 0);
"""

SQL_ANALYTICS = """
CREATE TABLE IF NOT EXISTS analytics (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    summary TEXT,
    differential TEXT,
    file_path TEXT,
    file_hash TEXT,
    exam_date DATE,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

SQL_ANALYTIC_MARKERS = """
CREATE TABLE IF NOT EXISTS analytic_markers (
    id SERIAL PRIMARY KEY,
    analytic_id INTEGER NOT NULL REFERENCES analytics(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    value DOUBLE PRECISION,
    unit TEXT,
    ref_min DOUBLE PRECISION,
    ref_max DOUBLE PRECISION
);
"""

SQL_IMAGING = """
CREATE TABLE IF NOT EXISTS imaging (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    type TEXT,
    summary TEXT,
    differential TEXT,
    file_path TEXT,
    file_hash TEXT,
    exam_date DATE,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

SQL_IMAGING_PATTERNS = """
CREATE TABLE IF NOT EXISTS imaging_patterns (
    id SERIAL PRIMARY KEY,
    imaging_id INTEGER NOT NULL REFERENCES imaging(id) ON DELETE CASCADE,
    pattern_text TEXT NOT NULL
);
"""

SQL_CLINICAL_NOTES = """
CREATE TABLE IF NOT EXISTS clinical_notes (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

SQL_TIMELINE_ITEMS = """
CREATE TABLE IF NOT EXISTS timeline_items (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

# ------------------------------
# TABLA NUEVA: MOTIVOS CANCELACIÓN
# ------------------------------

SQL_CANCELLATION_REASONS = """
CREATE TABLE IF NOT EXISTS cancellation_reasons (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reason_category TEXT,
    reason_text TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

# ------------------------------
# TABLAS NUEVAS: MÓDULO DE GUARDIA
# ------------------------------

SQL_GUARD_CASES = """
CREATE TABLE IF NOT EXISTS guard_cases (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT,
    age_group TEXT,
    sex TEXT,
    context TEXT,
    anonymized_summary TEXT,
    status TEXT DEFAULT 'open',
    patient_ref_id INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    last_activity_at TIMESTAMP DEFAULT NOW()
);
"""

SQL_GUARD_MESSAGES = """
CREATE TABLE IF NOT EXISTS guard_messages (
    id SERIAL PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES guard_cases(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    author_alias TEXT,
    raw_content TEXT,
    clean_content TEXT,
    moderation_status TEXT,
    moderation_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

SQL_GUARD_FAVORITES = """
CREATE TABLE IF NOT EXISTS guard_favorites (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    case_id INTEGER NOT NULL REFERENCES guard_cases(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

# ------------------------------
# TABLA NUEVA: ACTUALIDAD MÉDICA
# ------------------------------

SQL_MEDICAL_NEWS = """
CREATE TABLE IF NOT EXISTS medical_news (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT,
    source_name TEXT,
    source_url TEXT NOT NULL,
    published_at TIMESTAMP NULL,
    specialty_tags TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

# ------------------------------
# RESET COMPLETO DE BD (BORRA TODO)
# ------------------------------

SQL_RESET_ALL = """
TRUNCATE TABLE
  guard_messages,
  guard_favorites,
  guard_cases,
  analytic_markers,
  analytics,
  imaging_patterns,
  imaging,
  clinical_notes,
  timeline_items,
  cancellation_reasons,
  medical_news,
  patients,
  doctor_profiles,
  invitations,
  access_requests,
  users
RESTART IDENTITY CASCADE;
"""

# ------------------------------
# MIGRACIÓN COMPLETA
# ------------------------------

@router.post("/init")
def migrate_init(x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)

    try:
        with engine.begin() as conn:
            # Orden correcto (para evitar problemas de FK)
            conn.execute(text(SQL_USERS))
            conn.execute(text(SQL_DOCTOR_PROFILES))   # ⭐ PERFIL MÉDICO
            conn.execute(text(SQL_PATIENTS))
            conn.execute(text(SQL_ANALYTICS))
            conn.execute(text(SQL_ANALYTIC_MARKERS))
            conn.execute(text(SQL_IMAGING))
            conn.execute(text(SQL_IMAGING_PATTERNS))
            conn.execute(text(SQL_CLINICAL_NOTES))
            conn.execute(text(SQL_TIMELINE_ITEMS))
            conn.execute(text(SQL_CANCELLATION_REASONS))

            # 🔹 Tablas de guardia (De Guardia / Cartelera)
            conn.execute(text(SQL_GUARD_CASES))
            conn.execute(text(SQL_GUARD_MESSAGES))
            conn.execute(text(SQL_GUARD_FAVORITES))

            # 🔹 Extender doctor_profiles con alias de guardia (idempotente)
            conn.execute(text(SQL_DOCTOR_PROFILES_ALTER))

            # 🔹 Numeración clínica por médico (patient_number)
            conn.execute(text(SQL_PATIENTS_ALTER))
            conn.execute(text(SQL_PATIENTS_BACKFILL))

            # 🔹 Actualidad médica
            conn.execute(text(SQL_MEDICAL_NEWS))

        return {
            "status": "ok",
            "message": (
                "Migración completada: incluye doctor_profiles, exam_date, "
                "cancellation_reasons, tablas de guardia, numeración patient_number por médico "
                "y tabla medical_news para actualidad médica."
            ),
        }

    except Exception as e:
        raise HTTPException(500, f"Error en migración: {e}")


@router.post("/reset")
def migrate_reset_all(x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)

    try:
        with engine.begin() as conn:
            conn.execute(text(SQL_RESET_ALL))

        return {
            "status": "ok",
            "message": "BD limpiada: se han borrado todos los usuarios, pacientes y datos relacionados, y se han reseteado los IDs."
        }

    except Exception as e:
        raise HTTPException(500, f"Error en reset: {e}")
