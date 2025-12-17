# stripe_payments.py — Stripe FINAL v3 (Galenos)
# Checkout + Customer Portal + Webhooks (cerrado, sin cancelación directa)
#
# FIX v3 (Nora):
# - Además de client_reference_id (user.id), enlazamos el webhook también por email
#   (customer_details.email / customer_email) para cubrir casos donde el alta se hizo
#   fuera del checkout autenticado (p.ej. Pricing Table).
#
# Diseño:
# - Stripe gestiona pagos/cancelaciones
# - Galenos gestiona acceso, gracia (60 días) y archivado
# - Cancelación SIEMPRE vía Stripe Customer Portal (nunca /cancel en Galenos)

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
        common_kwargs = dict(
            mode="subscription",
            success_url=f"{FRONTEND_URL}/panel-medico?pro=success",
            cancel_url=f"{FRONTEND_URL}/panel-medico?pro=cancel",
            line_items=[{"price": PRICE_ID, "quantity": 1}],
            client_reference_id=str(user.id),
        )

        if getattr(user, "stripe_customer_id", None):
            session = stripe.checkout.Session.create(
                customer=user.stripe_customer_id,
                **common_kwargs,
            )
        else:
            session = stripe.checkout.Session.create(**common_kwargs)

        if session.customer and session.customer != getattr(user, "stripe_customer_id", None):
            user.stripe_customer_id = session.customer
            db.commit()

        return {"checkout_url": session.url}

    except Exception as e:
        raise HTTPException(500, f"Stripe error: {e}")


@router.get("/create-checkout-session-auth")
def create_checkout_session_auth(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return create_checkout_session(db=db, current_user=current_user)


@router.post("/portal")
def open_customer_portal(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user or not getattr(user, "stripe_customer_id", None):
        raise HTTPException(400, "No hay cliente Stripe asociado")

    try:
        portal = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=f"{FRONTEND_URL}/panel-medico",
        )
        return {"url": portal.url}
    except Exception as e:
        raise HTTPException(500, f"Stripe portal error: {e}")


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

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]

        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        client_ref = session.get("client_reference_id")

        email = None
        cd = session.get("customer_details") or {}
        if isinstance(cd, dict):
            email = cd.get("email") or None
        email = email or session.get("customer_email")

        user = None

        if customer_id:
            user = (
                db.query(models.User)
                .filter(models.User.stripe_customer_id == customer_id)
                .first()
            )

        if not user and client_ref:
            try:
                uid = int(client_ref)
                user = db.query(models.User).filter(models.User.id == uid).first()
            except Exception:
                user = None

        if not user and email:
            user = (
                db.query(models.User)
                .filter(models.User.email == email)
                .first()
            )

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
