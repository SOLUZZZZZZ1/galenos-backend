# stripe_payments.py — Stripe completo: Checkout + Webhook + Cancelación
import os
from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session
import stripe

from database import get_db
from auth import get_current_user
import models, crud

router = APIRouter(prefix="/billing", tags=["Billing"])

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://galenos.pro")

# --------------------------
# 1) CREAR CHECKOUT
# --------------------------
@router.get("/create-checkout-session")
def create_checkout_session(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    # 1) Bloquear si NO hay perfil médico
    profile = crud.get_doctor_profile_by_user(db, current_user.id)
    if not profile:
        raise HTTPException(
            status_code=400,
            detail="PROFILE_REQUIRED"
        )

    # 2) Stripe normal
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            success_url=f"{FRONTEND_URL}/pro?success=true",
            cancel_url=f"{FRONTEND_URL}/pro?canceled=true",
            line_items=[{
                "price": os.getenv("STRIPE_PRICE_ID"),
                "quantity": 1
            }],
            subscription_data={"trial_period_days": 3},
        )
        return {"checkout_url": session.url}
    except Exception as e:
        raise HTTPException(500, f"Stripe error: {e}")


# --------------------------
# 2) WEBHOOK
# --------------------------
@router.post("/webhook")
async def stripe_webhook(req: Request, db: Session = Depends(get_db)):
    payload = await req.body()
    sig_header = req.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.getenv("STRIPE_WEBHOOK_SECRET")
        )
    except Exception:
        raise HTTPException(400, "Webhook signature error")

    # ACTIVACIÓN
    if event["type"] == "customer.subscription.created":
        sub = event["data"]["object"]
        customer_id = sub["customer"]
        stripe_subscription_id = sub["id"]
        trial_end_ts = sub["trial_end"]

        user = db.query(models.User).filter(models.User.stripe_customer_id == customer_id).first()
        if user:
            user.is_pro = 1
            user.stripe_subscription_id = stripe_subscription_id
            from datetime import datetime
            user.trial_end = datetime.utcfromtimestamp(trial_end_ts)
            db.commit()

    # CANCELACIÓN DESDE STRIPE
    if event["type"] == "customer.subscription.deleted":
        sub = event["data"]["object"]
        customer_id = sub["customer"]

        user = db.query(models.User).filter(models.User.stripe_customer_id == customer_id).first()
        if user:
            user.is_pro = 0
            user.stripe_subscription_id = None
            db.commit()

    return {"status": "ok"}


# --------------------------
# 3) CANCELAR SUSCRIPCIÓN (médico pulsa botón)
# --------------------------
@router.post("/cancel")
def cancel_subscription(
    reason_category: str,
    reason_text: str = "",
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user or not user.stripe_subscription_id:
        raise HTTPException(400, "El usuario no tiene suscripción activa.")

    # GUARDAR MOTIVO
    mot = models.CancellationReason(
        user_id=user.id,
        reason_category=reason_category,
        reason_text=reason_text.strip()
    )
    db.add(mot)
    db.commit()

    # CANCELAR EN STRIPE
    try:
        stripe.Subscription.delete(user.stripe_subscription_id)
    except Exception as e:
        raise HTTPException(500, f"Error al cancelar en Stripe: {e}")

    # ACTUALIZAR BD
    user.is_pro = 0
    user.stripe_subscription_id = None
    db.commit()

    return {"status": "ok", "message": "Suscripción cancelada correctamente."}
