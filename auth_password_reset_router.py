# auth_password_reset_router.py — Olvidé mi contraseña (seguro) · Galenos.pro
#
# Flujo:
# 1) POST /auth/forgot-password  (email) -> responde SIEMPRE ok (anti-enumeración)
#    Si el email existe, envía enlace con token (one-time, expira).
# 2) POST /auth/reset-password   (token + nueva contraseña) -> valida token y cambia password_hash
#
# Seguridad:
# - Nunca revelamos si el email existe
# - Guardamos SOLO hash del token en BD
# - Token de un solo uso + expiración
# - Rate limit básico por email (DB: últimos N minutos) para evitar abuso

from __future__ import annotations

import os
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from database import get_db
from models import User, PasswordResetToken

# Intentamos reutilizar el hash de contraseña que ya use tu auth.py
# para que el login siga funcionando sin cambios.
def _hash_password_compatible(plain: str) -> str:
    try:
        import auth  # type: ignore
        # Caso A: auth.hash_password
        if hasattr(auth, "hash_password"):
            return auth.hash_password(plain)  # type: ignore
        # Caso B: auth.pwd_context (Passlib CryptContext)
        if hasattr(auth, "pwd_context"):
            return auth.pwd_context.hash(plain)  # type: ignore
    except Exception:
        pass

    # Fallback: bcrypt (Passlib)
    try:
        from passlib.context import CryptContext
        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return ctx.hash(plain)
    except Exception as e:
        raise RuntimeError(f"No se pudo hashear contraseña (instala passlib[bcrypt]): {e}")


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _now_utc() -> datetime:
    return datetime.utcnow()


# =========================
# Email sender (SMTP simple)
# =========================
def _send_reset_email(*, to_email: str, reset_url: str):
    """
    Envío por SMTP básico (Render-friendly).
    Variables:
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM
    Si no están, no falla: solo loguea (modo dev).
    """
    host = os.getenv("SMTP_HOST") or ""
    port = int(os.getenv("SMTP_PORT") or "587")
    user = os.getenv("SMTP_USER") or ""
    pwd = os.getenv("SMTP_PASS") or ""
    from_email = os.getenv("SMTP_FROM") or user or "no-reply@galenos.pro"

    subject = "Galenos — Restablecer contraseña"
    body = (
        "Has solicitado restablecer tu contraseña.\n\n"
        f"Enlace (válido por tiempo limitado):\n{reset_url}\n\n"
        "Si no has sido tú, ignora este mensaje.\n"
    )

    if not host or not user or not pwd:
        print("[RESET-PW] SMTP no configurado. Enlace:", reset_url)
        return

    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(user, pwd)
            smtp.send_message(msg)
    except Exception as e:
        # No revelamos nada al cliente, pero logueamos para diagnóstico
        print("[RESET-PW] Error enviando email:", repr(e))


# =========================
# API
# =========================
router = APIRouter(prefix="/auth", tags=["auth-password-reset"])


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ForgotPasswordOut(BaseModel):
    ok: bool = True
    message: str


class ResetPasswordIn(BaseModel):
    token: str = Field(..., min_length=16)
    new_password: str = Field(..., min_length=10, max_length=128)


class ResetPasswordOut(BaseModel):
    ok: bool = True
    message: str


def _rate_limit_ok(db: Session, *, user_id: int, window_minutes: int = 15, max_requests: int = 5) -> bool:
    """
    Rate limit básico: máximo N solicitudes por usuario dentro de la ventana.
    """
    since = _now_utc() - timedelta(minutes=window_minutes)
    n = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user_id, PasswordResetToken.created_at >= since)
        .count()
    )
    return n < max_requests


@router.post("/forgot-password", response_model=ForgotPasswordOut)
def forgot_password(payload: ForgotPasswordIn, db: Session = Depends(get_db)):
    # Respuesta genérica SIEMPRE
    generic = ForgotPasswordOut(
        ok=True,
        message="Si existe una cuenta con ese email, te enviaremos un enlace para restablecer la contraseña."
    )

    email = (payload.email or "").strip().lower()
    if not email:
        return generic

    user = db.query(User).filter(User.email == email).first()
    if not user:
        # Anti-enumeración: misma respuesta
        return generic

    # Rate limit suave
    if not _rate_limit_ok(db, user_id=user.id):
        return generic

    # Token fuerte y URL
    token = secrets.token_urlsafe(32)  # ~43 chars
    token_hash = _sha256_hex(token)
    expires_at = _now_utc() + timedelta(minutes=30)

    rec = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        used_at=None,
        created_at=_now_utc(),
    )
    db.add(rec)
    db.commit()

    # URL de reset (frontend)
    frontend_base = os.getenv("FRONTEND_URL") or os.getenv("PUBLIC_APP_URL") or ""
    if not frontend_base:
        # fallback: misma API (sirve para pruebas)
        frontend_base = os.getenv("API_PUBLIC_URL") or "http://localhost:5173"
    reset_url = f"{frontend_base.rstrip('/')}/reset-password?token={token}"

    _send_reset_email(to_email=email, reset_url=reset_url)
    return generic


@router.post("/reset-password", response_model=ResetPasswordOut)
def reset_password(payload: ResetPasswordIn, db: Session = Depends(get_db)):
    token = (payload.token or "").strip()
    new_pw = (payload.new_password or "").strip()

    if len(new_pw) < 10:
        raise HTTPException(400, "La nueva contraseña debe tener al menos 10 caracteres.")

    token_hash = _sha256_hex(token)

    rec = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == token_hash)
        .order_by(PasswordResetToken.created_at.desc())
        .first()
    )
    if not rec:
        raise HTTPException(400, "Token inválido o caducado.")

    if rec.used_at is not None:
        raise HTTPException(400, "Este enlace ya fue usado. Solicita uno nuevo.")

    if rec.expires_at < _now_utc():
        raise HTTPException(400, "Token caducado. Solicita uno nuevo.")

    user = db.query(User).filter(User.id == rec.user_id).first()
    if not user:
        raise HTTPException(400, "Token inválido.")

    # Cambiar contraseña
    try:
        user.password_hash = _hash_password_compatible(new_pw)
    except Exception as e:
        raise HTTPException(500, f"Error interno (hash): {e}")

    rec.used_at = _now_utc()
    db.add(user)
    db.add(rec)
    db.commit()

    return ResetPasswordOut(ok=True, message="Contraseña actualizada correctamente. Ya puedes iniciar sesión.")
