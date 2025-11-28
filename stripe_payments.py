# stripe_payments.py — Integración Stripe básica para Galenos.pro

import os
import stripe
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/billing", tags=["Billing"])

# Config Stripe
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID_GALENOS_PRO")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
FRONTEND_BASE = os.getenv("FRONTEND_URL", "https://galenos.vercel.app")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
    print("⚠️ STRIPE_SECRET_KEY no definida. Stripe no funcionará.")


@router.post("/create-checkout-session")
async def create_checkout_session(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Crea una sesión de Checkout para Galenos PRO (10 €/mes, 3 días de prueba).
    De momento no usa el usuario real, solo un email demo.
    """

    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        raise HTTPException(500, "Stripe no está configurado correctamente en el backend.")

    fake_email = "doctor-demo@galenos.pro"

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[
                {
                    "price": STRIPE_PRICE_ID,
                    "quantity": 1,
                }
            ],
            subscription_data={          # 👈 Aquí va el trial, bien cerrado
                "trial_period_days": 3
            },
            success_url=f"{FRONTEND_BASE}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_BASE}/billing/cancelled",
            customer_email=fake_email,
            metadata={
                "app": "galenos.pro"
            }
        )

        return {"checkout_url": session.url}

    except Exception as e:
        print("[Stripe] Error creando sesión de checkout:", repr(e))
        raise HTTPException(500, "No se ha podido iniciar el pago en Stripe.")
