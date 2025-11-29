import os
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import User, AccessRequest
from schemas import UserCreate, LoginRequest, TokenResponse, UserReturn, RegisterWithInviteRequest, AccessRequestCreate, AccessRequestReturn
from auth import register_user, login_user, get_current_user, create_invitation, register_user_with_invitation

import patients
import analytics
import imaging
import notes
import timeline
import stripe_payments  # 👈 Stripe (billing)
import migrate_galenos



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
# RUTA RAÍZ (para Render / healthcheck)
# ======================================================
@app.get("/")
def root():
    return {"ok": True, "message": "Galenos.pro API raíz"}


# ======================================================
# RUTA PING
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
# INVITACIONES (crear + registro desde invitación)
# ======================================================
@app.post("/auth/invitations/create")
def auth_invitations_create(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return create_invitation(db, current_user)


@app.post("/auth/register-from-invite", response_model=TokenResponse)
def auth_register_from_invite(
    data: RegisterWithInviteRequest,
    db: Session = Depends(get_db)
):
    token_response = register_user_with_invitation(data, db)
    return token_response


# ======================================================
# SOLICITUDES DE ACCESO (sin invitación)
# ======================================================
@app.post("/access-requests", response_model=AccessRequestReturn)
def create_access_request(
    data: AccessRequestCreate,
    db: Session = Depends(get_db)
):
    ar = AccessRequest(
        name=data.name,
        email=str(data.email),
        country=data.country,
        city=data.city,
        speciality=data.speciality,
        center=data.center,
        phone=data.phone,
        how_heard=data.how_heard,
        message=data.message,
    )
    db.add(ar)
    db.commit()
    db.refresh(ar)
    return ar


# ======================================================
# Incluir routers
# ======================================================
app.include_router(patients.router)
app.include_router(analytics.router)
app.include_router(imaging.router)
app.include_router(notes.router)
app.include_router(timeline.router)
app.include_router(stripe_payments.router)  # 👈 Billing / Stripe
app.include_router(migrate_galenos.router)
