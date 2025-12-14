# migrate_galenos.py — Migraciones Galenos.pro (completo)
# Incluye:
# - Tablas base
# - Perfil médico + alias de guardia
# - Pacientes con patient_number
# - Analíticas, imágenes, notas, timeline
# - Módulo De Guardia
# - ⭐ NUEVO: adjuntos por mensaje (guard_message_attachments)

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
    bio TEXT,
