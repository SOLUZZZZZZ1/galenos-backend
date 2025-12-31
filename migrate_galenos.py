import os
from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text
from database import engine

router = APIRouter(prefix="/admin/migrate-galenos", tags=["admin-migrate-galenos"])

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN") or "GalenosAdminToken@123"

# ✅ Versión actualizada (incluye VASCULAR)
MIGRATE_GALENOS_VERSION = "MSK_GEOMETRY_V1 + VASCULAR_GEOMETRY_V1"


def _auth(x_admin_token: str | None):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "Unauthorized")


SQL_USERS = (
    "CREATE TABLE IF NOT EXISTS users ("
    "id SERIAL PRIMARY KEY,"
    "email TEXT UNIQUE NOT NULL,"
    "password_hash TEXT NOT NULL,"
    "name TEXT,"
    "created_at TIMESTAMP DEFAULT NOW(),"
    "last_login TIMESTAMP NULL,"
    "is_active INTEGER DEFAULT 1,"
    "is_pro INTEGER DEFAULT 0,"
    "stripe_customer_id TEXT,"
    "stripe_subscription_id TEXT,"
    "trial_end TIMESTAMP"
    ");"
)

SQL_DOCTOR_PROFILES = (
    "CREATE TABLE IF NOT EXISTS doctor_profiles ("
    "id SERIAL PRIMARY KEY,"
    "user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
    "first_name TEXT,"
    "last_name TEXT,"
    "specialty TEXT,"
    "colegiado_number TEXT,"
    "phone TEXT,"
    "center TEXT,"
    "city TEXT,"
    "bio TEXT,"
    "guard_alias TEXT,"
    "guard_alias_locked INTEGER DEFAULT 0"
    ");"
)

SQL_PATIENTS = (
    "CREATE TABLE IF NOT EXISTS patients ("
    "id SERIAL PRIMARY KEY,"
    "doctor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
    "alias TEXT NOT NULL,"
    "age INTEGER,"
    "gender TEXT,"
    "notes TEXT,"
    "patient_number INTEGER,"
    "created_at TIMESTAMP DEFAULT NOW()"
    ");"
)

SQL_ANALYTICS = (
    "CREATE TABLE IF NOT EXISTS analytics ("
    "id SERIAL PRIMARY KEY,"
    "patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,"
    "summary TEXT,"
    "differential TEXT,"
    "file_path TEXT,"
    "file_hash TEXT,"
    "exam_date DATE,"
    "created_at TIMESTAMP DEFAULT NOW()"
    ");"
)

SQL_IMAGING = (
    "CREATE TABLE IF NOT EXISTS imaging ("
    "id SERIAL PRIMARY KEY,"
    "patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,"
    "type TEXT,"
    "summary TEXT,"
    "differential TEXT,"
    "file_path TEXT,"
    "file_hash TEXT,"
    "exam_date DATE,"
    "created_at TIMESTAMP DEFAULT NOW()"
    ");"
)

SQL_ANALYTICS_ALTER_SIZE_BYTES = (
    "ALTER TABLE analytics "
    "ADD COLUMN IF NOT EXISTS size_bytes BIGINT DEFAULT 0;"
)

SQL_IMAGING_ALTER_SIZE_BYTES = (
    "ALTER TABLE imaging "
    "ADD COLUMN IF NOT EXISTS size_bytes BIGINT DEFAULT 0;"
)

SQL_IMAGING_ALTER_AI_DESCRIPTION = (
    "ALTER TABLE imaging "
    "ADD COLUMN IF NOT EXISTS ai_description_draft TEXT;"
)

SQL_IMAGING_ALTER_AI_DESCRIPTION_TS = (
    "ALTER TABLE imaging "
    "ADD COLUMN IF NOT EXISTS ai_description_updated_at TIMESTAMP NULL;"
)

SQL_CLINICAL_NOTES = (
    "CREATE TABLE IF NOT EXISTS clinical_notes ("
    "id SERIAL PRIMARY KEY,"
    "patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,"
    "doctor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
    "title TEXT,"
    "content TEXT,"
    "created_at TIMESTAMP DEFAULT NOW()"
    ");"
)

# =========================
# MSK OVERLAY (GEOMETRÍA) — IA
# =========================
SQL_IMAGING_ALTER_MSK_OVERLAY_JSON = (
    "ALTER TABLE imaging "
    "ADD COLUMN IF NOT EXISTS msk_overlay_json JSONB;"
)

SQL_IMAGING_ALTER_MSK_OVERLAY_CONFIDENCE = (
    "ALTER TABLE imaging "
    "ADD C
