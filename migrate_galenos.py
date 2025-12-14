import os
from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text
from database import engine

router = APIRouter(prefix="/admin/migrate-galenos", tags=["admin-migrate-galenos"])

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN") or "GalenosAdminToken@123"


def _auth(x_admin_token: str | None):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "Unauthorized")


# =========================
# USUARIOS
# =========================
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


# =========================
# PERFIL MÉDICO
# =========================
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


SQL_DOCTOR_PROFILES_ALTER = """
ALTER TABLE doctor_profiles
    ADD COLUMN IF NOT EXISTS guard_alias TEXT;

ALTER TABLE doctor_profiles
    ADD COLUMN IF NOT EXISTS guard_alias_locked INTEGER DEFAULT 0;
"""


# =========================
# PACIENTES
# =========================
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


SQL_PATIENTS_ALTER = """
ALTER TABLE patients
    ADD COLUMN IF NOT EXISTS patient_number INTEGER;
"""


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


# =========================
# ANALÍTICAS
# =========================
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


# =========================
# IMAGING
# =========================
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


# =========================
# NOTAS CLÍNICAS
# =========================
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


# =========================
# TIMELINE
# =========================
SQL_TIMELINE_ITEMS = """
CREATE T
