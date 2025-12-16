import os
from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text
from database import engine

# migrate_community.py — Módulo Comunidad (SAFE, sin tocar Guardia/Pacientes)
# ✅ Tablas nuevas: community_cases + community_responses
# ✅ Migración idempotente: CREATE TABLE IF NOT EXISTS
# ✅ Pensado para escalar: visibilidad, status, last_activity_at

router = APIRouter(prefix="/admin/migrate-community", tags=["admin-migrate-community"])

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN") or "GalenosAdminToken@123"

MIGRATE_COMMUNITY_VERSION = "SAFE_COMMUNITY_V1"


def _auth(x_admin_token: str | None):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "Unauthorized")


SQL_COMMUNITY_CASES = (
    "CREATE TABLE IF NOT EXISTS community_cases ("
    "id SERIAL PRIMARY KEY,"
    "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
    "title TEXT,"
    "clinical_context TEXT,"
    "question TEXT,"
    "status TEXT DEFAULT 'open',"
    "visibility TEXT DEFAULT 'public',"
    "created_at TIMESTAMP DEFAULT NOW(),"
    "last_activity_at TIMESTAMP DEFAULT NOW()"
    ");"
)

SQL_COMMUNITY_CASES_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_community_cases_last_activity "
    "ON community_cases(last_activity_at DESC);"
)

SQL_COMMUNITY_RESPONSES = (
    "CREATE TABLE IF NOT EXISTS community_responses ("
    "id SERIAL PRIMARY KEY,"
    "case_id INTEGER NOT NULL REFERENCES community_cases(id) ON DELETE CASCADE,"
    "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
    "author_alias TEXT,"
    "content TEXT NOT NULL,"
    "created_at TIMESTAMP DEFAULT NOW()"
    ");"
)

SQL_COMMUNITY_RESPONSES_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_community_responses_case_id "
    "ON community_responses(case_id);"
)


@router.post("/init")
def migrate_init(x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)

    try:
        with engine.begin() as conn:
            conn.execute(text(SQL_COMMUNITY_CASES))
            conn.execute(text(SQL_COMMUNITY_CASES_INDEXES))
            conn.execute(text(SQL_COMMUNITY_RESPONSES))
            conn.execute(text(SQL_COMMUNITY_RESPONSES_INDEXES))

        return {
            "status": "ok",
            "version": MIGRATE_COMMUNITY_VERSION,
            "message": "Migración aplicada: módulo Comunidad (community_cases + community_responses)."
        }

    except Exception as e:
        raise HTTPException(500, f"Error en migración: {e}")
