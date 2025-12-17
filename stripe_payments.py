# stripe_payments.py — Stripe FINAL (Galenos)
# Checkout + Customer Portal + Webhooks
# Diseño cerrado y alineado con el modelo Galenos:
# - Stripe gestiona pagos/cancelaciones
# - Galenos gestiona acceso, gracia (60 días) y archivado
# - NO cancelación directa desde Galenos

import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session
import stripe

from database import get_db
from auth import get_current_user
import models

router = APIRouter(prefix="/billing", tags=["Billing"])

# --------------------------------------------------
# CONFIG
# --------------------------------------------------
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://galenos.pro")

PRICE_ID = os.getenv("STRIPE_PRICE_ID_GALENOS_PRO")

# --------------------------------------------------
# 1) CHECKOUT — MÉDICO LOGUEADO
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
        if user.stripe_customer_id:
            session = stripe.checkout.Session.create(
                mode="subscription",
                customer=user.stripe_customer_id,
                success_url=f"{FRONTEND_URL}/panel-medico?pro=success",
                cancel_url=f"{FRONTEND_URL}/panel-medico?pro=cancel",
                line_items=[{"price": PRICE_ID, "quantity": 1}],
            )
        else:
            session = stripe.checkout.Session.create(
                mode="subscription",
                success_url=f"{FRONTEND_URL}/panel-medico?pro=success",
                cancel_url=f"{FRONTEND_URL}/panel-medico?pro=cancel",
                line_items=[{"price": PRICE_ID, "quantity": 1}],
            )

        if session.customer and session.customer != user.stripe_customer_id:
            user.stripe_customer_id = session.customer
            db.commit()

        return {"checkout_url": session.url}

    except Exception as e:
        raise HTTPException(500, f"Stripe error: {e}")


# --------------------------------------------------
# 2) CUSTOMER PORTAL — GESTIONAR / CANCELAR
# --------------------------------------------------
@router.post("/portal")
def open_customer_portal(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user or not user.stripe_customer_id:
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

    # A) ACTIVACIÓN PRO
    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")

        if customer_id:
            user = (
                db.query(models.User)
                .filter(models.User.stripe_customer_id == customer_id)
                .first()
            )
            if user:
                user.is_pro = True
                user.stripe_subscription_id = subscription_id
                user.subscription_started_at = datetime.now(timezone.utc)
                user.subscription_ended_at = None
                user.cancel_at_period_end = False
                user.archived_at = None
                db.commit()

    # B) ACTUALIZACIÓN (cancel_at_period_end)
    if event_type == "customer.subscription.updated":
        sub = event["data"]["object"]
        customer_id = sub.get("customer")

        user = (
            db.query(models.User)
            .filter(models.User.stripe_customer_id == customer_id)
            .first()
        )
        if user:
            user.stripe_subscription_id = sub.get("id")
            user.cancel_at_period_end = bool(sub.get("cancel_at_period_end"))
            db.commit()

    # C) FIN REAL (INICIA GRACIA)
    if event_type == "customer.subscription.deleted":
        sub = event["data"]["object"]
        customer_id = sub.get("customer")

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
