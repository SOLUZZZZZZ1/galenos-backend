import os
from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from guardia_router import router as guardia_router
from doctor_profile_extra import router as doctor_profile_extra_router
from admin_doctors import router as admin_doctors_router
from medical_news_router import router as medical_news_router

from database import Base, engine, get_db
from models import User, AccessRequest
from schemas import (
    UserCreate,
    LoginRequest,
    TokenResponse,
    UserReturn,
    RegisterWithInviteRequest,
    AccessRequestCreate,
    AccessRequestReturn,
)
from auth import (
    register_user,
    login_user,
    get_current_user,
    create_invitation,
    register_user_with_invitation,
    register_master,
)

import patients
import analytics
import imaging
import notes
import timeline
import stripe_payments
import migrate_galenos
import doctor_profile


# ✅ NUEVO: router comparativa 6/12/18/24
import analytics_compare_router
import migrate_community


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
    description="Backend clínico con IA.",
)


# ======================================================
# CORS
# ======================================================
origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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


@app.get("/auth/me")
def auth_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "created_at": current_user.created_at,
        "is_pro": bool(getattr(current_user, "is_pro", 0)),
        "stripe_subscription_id": getattr(current_user, "stripe_subscription_id", None),
        "trial_end": getattr(current_user, "trial_end", None),
    }


# ======================================================
# INVITACIONES
# ======================================================
@app.post("/auth/invitations/create")
def auth_create_invite(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return create_invitation(db, current_user)


@app.post("/auth/register-from-invite", response_model=TokenResponse)
def auth_register_from_invite(
    data: RegisterWithInviteRequest,
    db: Session = Depends(get_db),
):
    return register_user_with_invitation(data, db)


# ======================================================
# REGISTER MASTER (solo una ejecución)
# ======================================================
@app.get("/auth/register-master")
def auth_register_master(
    secret: str = Query(...),
    db: Session = Depends(get_db),
):
    return register_master(db, secret)


# ======================================================
# ACCESS REQUESTS
# ======================================================
@app.post("/access-requests", response_model=AccessRequestReturn)
def create_access_request(
    data: AccessRequestCreate,
    db: Session = Depends(get_db),
):
    ar = AccessRequest(
        name=data.name,
        email=data.email,
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
# INCLUDE ROUTERS
# ======================================================
app.include_router(patients.router)
app.include_router(analytics.router)
app.include_router(imaging.router)
app.include_router(notes.router)
app.include_router(timeline.router)
app.include_router(stripe_payments.router)
app.include_router(migrate_galenos.router)
app.include_router(doctor_profile.router)
app.include_router(guardia_router)
app.include_router(doctor_profile_extra_router)
app.include_router(admin_doctors_router)
app.include_router(medical_news_router)

# ✅ NUEVO
app.include_router(analytics_compare_router.router)
app.include_router(migrate_community.router)
