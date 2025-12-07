import os
from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import User, AccessRequest
from schemas import (
    UserCreate,
    LoginRequest,
    TokenResponse,
    UserReturn,
    RegisterWithInviteRequest,
    AccessRequestCreate,
    AccessRequestReturn
)
from auth import (
    register_user,
    login_user,
    get_current_user,
    create_invitation,
    register_user_with_invitation,
    register_master
)

import patients
import analytics
import imaging
import notes
import timeline
import stripe_payments
import migrate_galenos
import doctor_profile  # 🔹 nuevo router de perfil médico


# ======================================================
# INIT DB
# ======================================================
def init_db():
    Base.metadata.create_all(bind=engine)

init_db()


# ======================================================
# APP FASTAPI
# ======================================================
app = FastAPI(
    title="Galenos.pro API",
    version="1.0.0",
    description="Backend clínico con IA."
)


# ======================================================
# CORS
# ======================================================
origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ======================================================
# HEALTHCHECK
# ======================================================
@app.get("/")
def root():
    return {"ok": True, "message": "Galenos.pro API"}


# ======================================================
# LOGIN / REGISTER NORMAL
# ======================================================
@app.post("/auth/register", response_model=UserReturn)
def auth_register(data: UserCreate, db: Session = Depends(get_db)):
    return register_user(data, db)


@app.post("/auth/login", response_model=TokenResponse)
def auth_login(data: LoginRequest, db: Session = Depends(get_db)):
    return login_user(data, db)


@app.get("/auth/me", response_model=UserReturn)
def auth_me(current_user: User = Depends(get_current_user)):
    return current_user


# ======================================================
# INVITACIONES
# ======================================================
@app.post("/auth/invitations/create")
def auth_create_invite(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return create_invitation(db, current_user)


@app.post("/auth/register-from-invite", response_model=TokenResponse)
def auth_register_from_invite(
    data: RegisterWithInviteRequest,
    db: Session = Depends(get_db)
):
    return register_user_with_invitation(data, db)


# ======================================================
# REGISTER MASTER (solo una ejecución)
# ======================================================
@app.get("/auth/register-master")
def auth_register_master(
    secret: str = Query(...),
    db: Session = Depends(get_db)
):
    return register_master(db, secret)


# ======================================================
# ACCESS REQUESTS
# ======================================================
@app.post("/access-requests", response_model=Acce_
