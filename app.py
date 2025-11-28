# app.py — Backend principal de Galenos.pro

import os
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from openai import OpenAI

from database import Base, engine, get_db
from models import User
from schemas import UserCreate, LoginRequest, TokenResponse, UserReturn
from auth import register_user, login_user, get_current_user
import patients
import analytics
import imaging
import notes
import timeline


# ======================================================
# Inicializar BD (crear tablas si no existen)
# ======================================================
def init_db():
    Base.metadata.create_all(bind=engine)

init_db()


# ======================================================
# FastAPI APP
# ======================================================
app = FastAPI(
    title="Galenos.pro API",
    description="Backend clínico con IA para médicos (analíticas + imágenes + notas + timeline).",
    version="1.0.0",
)


# ======================================================
# CORS
# ======================================================
cors_origins_raw = os.getenv("CORS_ORIGINS", "*")
if cors_origins_raw == "*" or not cors_origins_raw.strip():
    origins = ["*"]
else:
    origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ======================================================
# RUTAS BÁSICAS
# ======================================================
@app.get("/ping")
def ping():
    return {"ok": True, "message": "Galenos.pro backend vivo", "version": "1.0.0"}


# ======================================================
# AUTH — Registro y login de médicos
# ======================================================
@app.post("/auth/register", response_model=UserReturn)
def auth_register(
    data: UserCreate,
    db: Session = Depends(get_db)
):
    user = register_user(data, db)
    return user


@app.post("/auth/login", response_model=TokenResponse)
def auth_login(
    data: LoginRequest,
    db: Session = Depends(get_db)
):
    token = login_user(data, db)
    return token


@app.get("/auth/me", response_model=UserReturn)
def auth_me(current_user: User = Depends(get_current_user)):
    return current_user


# ======================================================
# Incluir routers
# ======================================================
app.include_router(patients.router)
app.include_router(analytics.router)
app.include_router(imaging.router)
app.include_router(notes.router)
app.include_router(timeline.router)
