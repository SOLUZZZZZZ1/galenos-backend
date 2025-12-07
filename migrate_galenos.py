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
# MIGRACIÓN COMPLETA
# ------------------------------

@router.post("/init")
def migrate_init(x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)

    try:
        with engine.begin() as conn:
            # Orden correcto (para evitar problemas de FK)
            conn.execute(text(SQL_USERS))
            conn.execute(text(SQL_DOCTOR_PROFILES))   # ⭐ NUEVO PERFIL MÉDICO
            conn.execute(text(SQL_PATIENTS))
            conn.execute(text(SQL_ANALYTICS))
            conn.execute(text(SQL_ANALYTIC_MARKERS))
            conn.execute(text(SQL_IMAGING))
            conn.execute(text(SQL_IMAGING_PATTERNS))
            conn.execute(text(SQL_CLINICAL_NOTES))
            conn.execute(text(SQL_TIMELINE_ITEMS))
            conn.execute(text(SQL_CANCELLATION_REASONS))

        return {
            "status": "ok",
            "message": "Migración completada: incluye doctor_profiles, exam_date y cancellation_reasons."
        }

    except Exception as e:
        raise HTTPException(500, f"Error en migración: {e}")
