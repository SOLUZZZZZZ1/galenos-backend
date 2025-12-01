# stripe_payments.py — Integración Stripe para Galenos.pro (PRO real)
import os
from datetime import datetime

import stripe
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from models import User
from auth import get_current_user

router = APIRouter(prefix="/billing", tags=["Billing"])

# ======================================================
# Configuración Stripe desde variables de entorno
# ======================================================
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")  # sk_test_... o sk_live_...
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID_GALENOS_PRO")  # price_...
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")  # whsec_...
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://frontend-galenos.vercel.app")


if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
    print("[Stripe] ⚠️ STRIPE_SECRET_KEY no está definida. Stripe no funcionará.")


# ======================================================
# Endpoint: crear sesión de Checkout (Galenos PRO)
# ======================================================
@router.get("/create-checkout-session")
async def create_checkout_session(current_user: User = Depends(get_current_user)):
    """
    Crea una sesión de Checkout para Galenos PRO (10 €/mes, 3 días de prueba).
    Devuelve una URL de Stripe para redirigir al usuario.
    El usuario debe estar autenticado: enlazamos la suscripción a su email.
    """
    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        raise HTTPException(
            status_code=500,
            detail="Stripe no está configurado correctamente en el backend.",
        )

    try:
        customer_email = current_user.email

        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[
                {
                    "price": STRIPE_PRICE_ID,
                    "quantity": 1,
                }
            ],
            allow_promotion_codes=True,
            subscription_data={
                "trial_period_days": 3,
            },
            success_url=f"{FRONTEND_URL}/panel-medico?checkout=success",
            cancel_url=f"{FRONTEND_URL}/panel-medico?checkout=cancel",
            customer_email=customer_email,
            metadata={
                "app": "galenos.pro",
                "user_id": str(current_user.id),
                "email": customer_email,
            },
        )

        return {"checkout_url": session.url}

    except Exception as e:
        print("[Stripe] Error creando sesión de checkout:", repr(e))
        raise HTTPException(
            status_code=500,
            detail="No se ha podido iniciar el pago en Stripe.",
        )


# ======================================================
# Endpoint: estado de facturación (simple)
# ======================================================
@router.get("/status")
def billing_status(current_user: User = Depends(get_current_user)):
    """
    Devuelve el estado PRO actual del usuario según la base de datos.
    """
    return {
        "is_pro": bool(current_user.is_pro),
        "stripe_customer_id": current_user.stripe_customer_id,
        "stripe_subscription_id": current_user.stripe_subscription_id,
        "trial_end": current_user.trial_end.isoformat() if current_user.trial_end else None,
    }


# ======================================================
# Endpoint: webhook de Stripe
# ======================================================
@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Webhook de Stripe:
    - Verifica la firma con STRIPE_WEBHOOK_SECRET.
    - Maneja eventos importantes (de momento solo checkout.session.completed).
    - Marca al médico como PRO en la base de datos.
    """
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Stripe webhook no está configurado en el backend.",
        )

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        # Cuerpo inválido
        raise HTTPException(status_code=400, detail="Payload inválido")
    except stripe.error.SignatureVerificationError:
        # Firma inválida
        raise HTTPException(status_code=400, detail="Firma inválida")

    event_type = event.get("type")
    data_object = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        customer_email = (
            (data_object.get("customer_details") or {}).get("email")
            or data_object.get("customer_email")
        )
        subscription_id = data_object.get("subscription")
        customer_id = data_object.get("customer")

        print(f"[Stripe] ✅ checkout.session.completed para {customer_email}")

        # Obtenemos trial_end desde la suscripción (si existe)
        trial_end_dt = None
        if subscription_id:
            try:
                sub = stripe.Subscription.retrieve(subscription_id)
                if sub.trial_end:
                    trial_end_dt = datetime.utcfromtimestamp(sub.trial_end)
            except Exception as e:
                print("[Stripe] ⚠️ No se pudo obtener la suscripción para trial_end:", repr(e))

        if customer_email:
            user = db.query(User).filter(User.email == customer_email).first()
            if user:
                user.is_pro = 1
                user.stripe_customer_id = customer_id
                user.stripe_subscription_id = subscription_id
                user.trial_end = trial_end_dt
                db.commit()
                print(f"[Stripe] 🔓 Usuario PRO activado en BD: {customer_email}")
            else:
                print(f"[Stripe] ⚠️ No se encontró usuario con email {customer_email}")

    # Otros eventos se pueden manejar más adelante: invoice.paid, customer.subscription.deleted, etc.
    return JSONResponse({"received": True})
