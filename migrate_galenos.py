import os
from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text
from database import engine

router = APIRouter(prefix="/admin/migrate-galenos", tags=["admin-migrate-galenos"])

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN") or "GalenosAdminToken@123"

MIGRATE_GALENOS_VERSION = "SAFE_NO_TRIPLE_QUOTES_V2"


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

SQL_TIMELINE_ITEMS = (
    "CREATE TABLE IF NOT EXISTS timeline_items ("
    "id SERIAL PRIMARY KEY,"
    "patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,"
    "item_type TEXT NOT NULL,"
    "item_id INTEGER NOT NULL,"
    "created_at TIMESTAMP DEFAULT NOW()"
    ");"
)

# =========================
# GUARDIA (COMPARTIDA)
# =========================

SQL_GUARD_CASES = (
    "CREATE TABLE IF NOT EXISTS guard_cases ("
    "id SERIAL PRIMARY KEY,"
    "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
    "title TEXT,"
    "age_group TEXT,"
    "sex TEXT,"
    "context TEXT,"
    "anonymized_summary TEXT,"
    "status TEXT DEFAULT 'open',"
    "patient_ref_id INTEGER,"
    "created_at TIMESTAMP DEFAULT NOW(),"
    "last_activity_at TIMESTAMP DEFAULT NOW(),"
    "visibility TEXT DEFAULT 'public'"
    ");"
)

SQL_GUARD_CASES_ALTER_VISIBILITY = (
    "ALTER TABLE guard_cases "
    "ADD COLUMN IF NOT EXISTS visibility TEXT DEFAULT 'public';"
)

SQL_GUARD_MESSAGES = (
    "CREATE TABLE IF NOT EXISTS guard_messages ("
    "id SERIAL PRIMARY KEY,"
    "case_id INTEGER NOT NULL REFERENCES guard_cases(id) ON DELETE CASCADE,"
    "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
    "author_alias TEXT,"
    "raw_content TEXT,"
    "clean_content TEXT,"
    "moderation_status TEXT,"
    "moderation_reason TEXT,"
    "created_at TIMESTAMP DEFAULT NOW()"
    ");"
)

SQL_GUARD_FAVORITES = (
    "CREATE TABLE IF NOT EXISTS guard_favorites ("
    "id SERIAL PRIMARY KEY,"
    "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
    "case_id INTEGER NOT NULL REFERENCES guard_cases(id) ON DELETE CASCADE,"
    "created_at TIMESTAMP DEFAULT NOW()"
    ");"
)

SQL_GUARD_MESSAGE_ATTACHMENTS = (
    "CREATE TABLE IF NOT EXISTS guard_message_attachments ("
    "id SERIAL PRIMARY KEY,"
    "message_id INTEGER NOT NULL REFERENCES guard_messages(id) ON DELETE CASCADE,"
    "kind TEXT NOT NULL CHECK (kind IN ('analytic','imaging')),"
    "ref_id INTEGER NOT NULL"
    ");"
)


@router.post("/init")
def migrate_init(x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)

    try:
        with engine.begin() as conn:
            conn.execute(text(SQL_USERS))
            conn.execute(text(SQL_DOCTOR_PROFILES))
            conn.execute(text(SQL_PATIENTS))

            conn.execute(text(SQL_ANALYTICS))
            conn.execute(text(SQL_IMAGING))
            conn.execute(text(SQL_CLINICAL_NOTES))
            conn.execute(text(SQL_TIMELINE_ITEMS))

            conn.execute(text(SQL_GUARD_CASES))
            conn.execute(text(SQL_GUARD_CASES_ALTER_VISIBILITY))
            conn.execute(text(SQL_GUARD_MESSAGES))
            conn.execute(text(SQL_GUARD_FAVORITES))
            conn.execute(text(SQL_GUARD_MESSAGE_ATTACHMENTS))

        return {
            "status": "ok",
            "version": MIGRATE_GALENOS_VERSION,
            "message": "Migración aplicada: guardia compartida + visibility + favoritos."
        }

    except Exception as e:
        raise HTTPException(500, f"Error en migración: {e}")
