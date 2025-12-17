# stripe_payments.py — Stripe FINAL v4 (Galenos) ✅
# Cierre robusto: Portal siempre funciona tras suscribirse
#
# FIX v4 (Nora):
# 1) En el checkout autenticado, si el usuario no tiene stripe_customer_id:
#    - buscamos Customer por email en Stripe y lo reutilizamos, o lo creamos.
#    - pasamos SIEMPRE customer=... a checkout.Session.create
#    => garantiza que el customer_id existe y queda asociado al usuario.
# 2) Añadimos metadata (user_id, user_email) al Checkout (y subscription_data.metadata)
#    para que el webhook pueda enlazar de forma inequívoca.
# 3) En /portal, si falta stripe_customer_id, intentamos recuperarlo por email y guardarlo.

import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session
import stripe

from database import get_db
from auth import get_current_user
import models

router = APIRouter(prefix="/billing", tags=["Billing"])

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://galenos.pro")

PRICE_ID = os.getenv("STRIPE_PRICE_ID_GALENOS_PRO") or os.getenv("STRIPE_PRICE_ID")


# ------------------------------
# Helpers Stripe
# ------------------------------
def _get_or_create_customer_by_email(email: str) -> str:
    """Devuelve un customer_id (cus_...) existente por email o crea uno nuevo."""
    if not email:
        raise HTTPException(400, "Email requerido para crear cliente Stripe.")

    try:
        # Stripe Search (si está disponible) es lo más exacto.
        # Si no está disponible en tu cuenta, caerá al except y usaremos list().
        res = stripe.Customer.search(query=f'email:"{email}"', limit=1)
        data = getattr(res, "data", None) or res.get("data", [])
        if data:
            return data[0]["id"]
    except Exception:
        # Fallback seguro: listar por email (más lento pero funciona)
        try:
            lst = stripe.Customer.list(email=email, limit=1)
            data = getattr(lst, "data", None) or lst.get("data", [])
            if data:
                return data[0]["id"]
        except Exception:
            pass

    # Crear si no existe
    cust = stripe.Customer.create(email=email)
    return cust["id"]


# --------------------------------------------------
# 1) CHECKOUT — MÉDICO LOGUEADO (recomendado)
# --------------------------------------------------
@router.get("/create-checkout-session")
def create_checkout_session(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not PRICE_ID:
        raise HTTPException(500, "STRIPE_PRICE_ID_GALENOS_PRO no configurada")

    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user:
        raise HTTPException(401, "Usuario no encontrado")

    try:
        # ✅ Aseguramos SIEMPRE un customer_id consistente
        customer_id = getattr(user, "stripe_customer_id", None)
        if not customer_id:
            customer_id = _get_or_create_customer_by_email(user.email)
            user.stripe_customer_id = customer_id
            db.commit()

        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            success_url=f"{FRONTEND_URL}/panel-medico?pro=success",
            cancel_url=f"{FRONTEND_URL}/panel-medico?pro=cancel",
            line_items=[{"price": PRICE_ID, "quantity": 1}],
            client_reference_id=str(user.id),
            metadata={
                "user_id": str(user.id),
                "user_email": user.email,
                "app": "galenos",
            },
            subscription_data={
                "metadata": {
                    "user_id": str(user.id),
                    "user_email": user.email,
                    "app": "galenos",
                }
            },
        )

        return {"checkout_url": session.url}

    except Exception as e:
        raise HTTPException(500, f"Stripe error: {e}")


# Compatibilidad con frontend antiguo
@router.get("/create-checkout-session-auth")
def create_checkout_session_auth(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return create_checkout_session(db=db, current_user=current_user)


# --------------------------------------------------
# 2) CUSTOMER PORTAL — GESTIONAR / CANCELAR
# --------------------------------------------------
@router.post("/portal")
def open_customer_portal(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user:
        raise HTTPException(401, "Usuario no encontrado")

    # ✅ Si falta customer_id, intentamos recuperarlo por email
    if not getattr(user, "stripe_customer_id", None):
        try:
            customer_id = _get_or_create_customer_by_email(user.email)
            user.stripe_customer_id = customer_id
            db.commit()
        except Exception:
            raise HTTPException(400, "No hay cliente Stripe asociado")

    try:
        portal = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=f"{FRONTEND_URL}/panel-medico",
        )
        return {"url": portal.url}
    except Exception as e:
        raise HTTPException(500, f"Stripe portal error: {e}")


# --------------------------------------------------
# 3) WEBHOOK — FUENTE DE VERDAD DE ESTADOS
# --------------------------------------------------
@router.post("/webhook")
async def stripe_webhook(req: Request, db: Session = Depends(get_db)):
    payload = await req.body()
    sig_header = req.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception:
        raise HTTPException(400, "Webhook signature error")

    event_type = event["type"]

    # A) Checkout completado (alta PRO)
    if event_type == "checkout.session.completed":
        session = event["data"]["object"]

        customer_id = session.get("customer")
        subscription_id = session.get("subscription")

        # Enlace más fiable: metadata.user_id
        md = session.get("metadata") or {}
        user_id = md.get("user_id") or session.get("client_reference_id")

        user = None
        if user_id:
            try:
                uid = int(user_id)
                user = db.query(models.User).filter(models.User.id == uid).first()
            except Exception:
                user = None

        # Fallback por email
        if not user:
            email = None
            cd = session.get("customer_details") or {}
            if isinstance(cd, dict):
                email = cd.get("email") or None
            email = email or session.get("customer_email")
            if email:
                user = db.query(models.User).filter(models.User.email == email).first()

        if user:
            if customer_id and customer_id != getattr(user, "stripe_customer_id", None):
                user.stripe_customer_id = customer_id
            if subscription_id:
                user.stripe_subscription_id = subscription_id

            user.is_pro = True
            user.subscription_started_at = datetime.now(timezone.utc)
            user.subscription_ended_at = None
            user.cancel_at_period_end = False
            user.archived_at = None
            db.commit()

    # B) Actualización (cancel_at_period_end)
    if event_type == "customer.subscription.updated":
        sub = event["data"]["object"]
        customer_id = sub.get("customer")

        user = None
        if customer_id:
            user = (
                db.query(models.User)
                .filter(models.User.stripe_customer_id == customer_id)
                .first()
            )

        if user:
            user.stripe_subscription_id = sub.get("id")
            user.cancel_at_period_end = bool(sub.get("cancel_at_period_end"))
            db.commit()

    # C) Fin real (inicia gracia)
    if event_type == "customer.subscription.deleted":
        sub = event["data"]["object"]
        customer_id = sub.get("customer")

        user = None
        if customer_id:
            user = (
                db.query(models.User)
                .filter(models.User.stripe_customer_id == customer_id)
                .first()
            )

        if user:
            user.is_pro = False
            user.subscription_ended_at = datetime.now(timezone.utc)
            user.cancel_at_period_end = False
            user.stripe_subscription_id = None
            db.commit()

    return {"status": "ok"}
