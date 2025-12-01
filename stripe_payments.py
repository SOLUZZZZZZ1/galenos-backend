
# stripe_payments.py — Integración Stripe para Galenos.pro (PRO real, sin exigir token en este endpoint)
import os
from datetime import datetime, timedelta

import stripe
from fastapi import APIRouter, HTTPException, Request, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from models import User

router = APIRouter(prefix="/billing", tags=["Billing"])

# ======================================================
# Configuración Stripe desde variables de entorno
# ======================================================

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://galenos.pro")
TRIAL_DAYS = int(os.getenv("STRIPE_TRIAL_DAYS", "3"))

if not STRIPE_SECRET_KEY:
    print("[Stripe] ⚠️ STRIPE_SECRET_KEY no configurada. El módulo de pagos no estará operativo.")
else:
    stripe.api_key = STRIPE_SECRET_KEY


# ======================================================
# 1) Crear sesión de checkout (como ayer: SIN email obligatorio)
# ======================================================

@router.get("/create-checkout-session")
def create_checkout_session(
    email: str | None = Query(
        None,
        description="Correo del médico (opcional; si no se envía, Stripe pedirá el email en el checkout)",
    ),
    db: Session = Depends(get_db),
):
    """Crea una sesión de checkout de Stripe para activar Galenos PRO.

    - No exige token de autenticación (se puede llamar desde la landing).
    - El parámetro `email` es OPCIONAL.
    - Si no se envía correo, Stripe lo pedirá en el formulario de pago.
    """

    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        raise HTTPException(
            status_code=500,
            detail="Stripe no está configurado correctamente en el backend.",
        )

    customer_email = email or None

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[
                {
                    "price": STRIPE_PRICE_ID,
                    "quantity": 1,
                }
            ],
            payment_method_types=["card"],
            customer_email=customer_email,
            subscription_data={
                "trial_period_days": TRIAL_DAYS,
            },
            success_url=f"{FRONTEND_URL}/panel-medico?status=success",
            cancel_url=f"{FRONTEND_URL}/panel-medico?status=cancel",
        )

        print(f"[Stripe] ✅ Sesión de checkout creada para {customer_email}")
        return {"checkout_url": session.url}

    except Exception as e:
        print(f"[Stripe] ❌ Error creando sesión de checkout: {e}")
        raise HTTPException(
            status_code=500,
            detail="No se ha podido crear la sesión de pago en Stripe.",
        )


# ======================================================
# 2) Webhook de Stripe
# ======================================================

@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Webhook de Stripe para activar/cancelar Galenos PRO.

    De momento solo procesamos `checkout.session.completed`, suficiente
    para dejar al usuario en modo PRO después de completar el pago.
    """
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=500,
            detail="El webhook de Stripe no está configurado en el backend.",
        )

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        # Payload inválido
        print("[Stripe] ❌ Payload inválido en webhook.")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        # Firma incorrecta
        print("[Stripe] ❌ Firma inválida en webhook.")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    print(f"[Stripe] 📩 Evento recibido: {event_type}")

    # --------------------------------------------------
    # Activación PRO tras completar el checkout
    # --------------------------------------------------
    if event_type == "checkout.session.completed":
        session_obj = event["data"]["object"]

        customer_email = (
            session_obj.get("customer_details", {}) or {}
        ).get("email")
        subscription_id = session_obj.get("subscription")
        customer_id = session_obj.get("customer")

        # Por simplicidad, fijamos el trial_end a ahora + TRIAL_DAYS
        trial_end_dt = datetime.utcnow() + timedelta(days=TRIAL_DAYS)

        if customer_email:
            user = db.query(User).filter(User.email == customer_email).first()
            if user:
                user.is_pro = 1
                user.stripe_customer_id = str(customer_id) if customer_id else None
                user.stripe_subscription_id = (
                    str(subscription_id) if subscription_id else None
                )
                user.trial_end = trial_end_dt
                db.commit()
                print(f"[Stripe] 🔓 Usuario PRO activado en BD: {customer_email}")
            else:
                print(
                    f"[Stripe] ⚠️ No se encontró usuario con email {customer_email}"
                )
        else:
            print(
                "[Stripe] ⚠️ checkout.session.completed recibido sin customer_email"
            )

    # Aquí puedes manejar otros eventos (cancelaciones, etc.) más adelante

    return JSONResponse({"received": True})
