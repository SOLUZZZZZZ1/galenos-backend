# migrate_galenos.py — Migraciones básicas para Galenos.pro (idempotentes)
#
# Crea y asegura las tablas:
# - users
# - patients
# - analytics
# - analytic_markers
# - imaging
# - imaging_patterns
# - clinical_notes
# - timeline_items
# + Campos PRO para Stripe en users (is_pro, stripe_customer_id, stripe_subscription_id, trial_end)
# + Campos clínicos en patients (age, gender, notes)
# + Campos file_hash en analytics e imaging
# + Campos exam_date (DATE) en analytics e imaging
#
# Uso:
# 1) En app.py:
#       import migrate_galenos
#       app.include_router(migrate_galenos.router)
#
# 2) Llamar al endpoint:
#    POST /admin/migrate-galenos/init  con cabecera:  x-admin-token: TU_TOKEN
#
# 3) Se crearán las tablas si no existen y se añadirán las columnas extra si faltan (no borra datos).

import os
from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text
from database import engine

router = APIRouter(prefix="/admin/migrate-galenos", tags=["admin-migrate-galenos"])

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN") or "GalenosAdminToken@123"


# --- Autenticación simple admin ---
def _auth(x_admin_token: str | None):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "Unauthorized")


# ==============================
# SQL DE CREACIÓN DE TABLAS
# ==============================

SQL_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP NULL,
    is_active INTEGER DEFAULT 1
);
"""

SQL_PATIENTS = """
CREATE TABLE IF NOT EXISTS patients (
    id SERIAL PRIMARY KEY,
    doctor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

# Extensión de patients con campos clínicos básicos
SQL_PATIENTS_EXTENDED = """
ALTER TABLE patients ADD COLUMN IF NOT EXISTS age INTEGER;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS gender TEXT;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS notes TEXT;
"""

SQL_ANALYTICS = """
CREATE TABLE IF NOT EXISTS analytics (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    summary TEXT,
    differential TEXT,
    file_path TEXT,
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
    item_type TEXT NOT NULL, -- 'patient' | 'analytic' | 'imaging' | 'note'
    item_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

SQL_INDEXES = """
-- Índices útiles
CREATE INDEX IF NOT EXISTS idx_patients_doctor_id ON patients (doctor_id);
CREATE INDEX IF NOT EXISTS idx_analytics_patient_id ON analytics (patient_id);
CREATE INDEX IF NOT EXISTS idx_markers_analytic_id ON analytic_markers (analytic_id);
CREATE INDEX IF NOT EXISTS idx_imaging_patient_id ON imaging (patient_id);
CREATE INDEX IF NOT EXISTS idx_notes_patient_id ON clinical_notes (patient_id);
CREATE INDEX IF NOT EXISTS idx_timeline_patient_id ON timeline_items (patient_id);
"""

# Campos PRO para Stripe en users
SQL_USERS_STRIPE = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_pro INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_end TIMESTAMP;
"""

# Campos extra para hashes de archivo
SQL_ANALYTICS_EXTENDED = """
ALTER TABLE analytics ADD COLUMN IF NOT EXISTS file_hash TEXT;
"""

SQL_IMAGING_EXTENDED = """
ALTER TABLE imaging ADD COLUMN IF NOT EXISTS file_hash TEXT;
"""

# Campos fecha clínica real
SQL_ANALYTICS_EXAM_DATE = """
ALTER TABLE analytics ADD COLUMN IF NOT EXISTS exam_date DATE;
"""

SQL_IMAGING_EXAM_DATE = """
ALTER TABLE imaging ADD COLUMN IF NOT EXISTS exam_date DATE;
"""


# ==============================
# ENDPOINTS DE MIGRACIÓN
# ==============================

@router.post("/init")
def migrate_init(x_admin_token: str | None = Header(None)):
    """
    Crea todas las tablas de Galenos.pro si no existen y añade los campos extra
    (clínicos, PRO de Stripe, hashes de archivo y exam_date). No borra ni modifica datos existentes.
    """
    _auth(x_admin_token)

    try:
        with engine.begin() as conn:
            # Tablas base
            conn.execute(text(SQL_USERS))
            conn.execute(text(SQL_PATIENTS))
            conn.execute(text(SQL_ANALYTICS))
            conn.execute(text(SQL_ANALYTIC_MARKERS))
            conn.execute(text(SQL_IMAGING))
            conn.execute(text(SQL_IMAGING_PATTERNS))
            conn.execute(text(SQL_CLINICAL_NOTES))
            conn.execute(text(SQL_TIMELINE_ITEMS))
            conn.execute(text(SQL_INDEXES))

            # Extender patients con campos clínicos
            conn.execute(text(SQL_PATIENTS_EXTENDED))

            # Campos extra para archivos (hash)
            conn.execute(text(SQL_ANALYTICS_EXTENDED))
            conn.execute(text(SQL_IMAGING_EXTENDED))

            # Campos exam_date (fecha clínica)
            conn.execute(text(SQL_ANALYTICS_EXAM_DATE))
            conn.execute(text(SQL_IMAGING_EXAM_DATE))

            # Campos PRO (Stripe) en users
            conn.execute(text(SQL_USERS_STRIPE))

        return {
            "status": "ok",
            "message": "Tablas de Galenos y campos extra (PRO + hashes + exam_date) creados/asegurados correctamente."
        }
    except Exception as e:
        raise HTTPException(500, f"Error en migración Galenos: {e}")


@router.get("/check")
def migrate_check(x_admin_token: str | None = Header(None)):
    """
    Pequeña ruta para comprobar que el router admin responde.
    No ejecuta migraciones, solo sirve de 'ping' para admins.
    """
    _auth(x_admin_token)
    return {"status": "ok", "message": "migrate_galenos router activo."}
