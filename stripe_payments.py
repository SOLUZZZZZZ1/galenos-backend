# stripe_payments.py — Galenos.pro · Stripe PRO (restaurado como anoche, sin auth y tolerante con variables)
import os
from datetime import datetime
from typing import Optional

import stripe
from fastapi import APIRouter, HTTPException, Request, Query, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from models import User

router = APIRouter(prefix="/billing", tags=["Billing"])

# ======================================================
# Configuración Stripe desde variables de entorno
# (soporta nombres "antiguos" para no romper nada)
# ======================================================

# Intentamos varias posibles claves secretas por compatibilidad.
STRIPE_SECRET_KEY: Optional[str] = (
    os.getenv("STRIPE_SECRET_KEY")
    or os.getenv("STRIPE_SECRET")
    or os.getenv("STRIPE_API_KEY")
)

# Intentamos varios nombres de PRICE_ID por compatibilidad.
STRIPE_PRICE_ID: Optional[str] = (
    os.getenv("STRIPE_PRICE_ID_GALENOS_PRO")
    or os.getenv("STRIPE_PRICE_ID")
    or os.getenv("PRICE_ID")
    or os.getenv("STRIPE_PRICE")
)

# Webhook secret (para verificar la firma)
STRIPE_WEBHOOK_SECRET: Optional[str] = os.getenv("STRIPE_WEBHOOK_SECRET")

# URL del frontend para redirecciones tras el pago
FRONTEND_URL: str = os.getenv("FRONTEND_URL", "https://galenos.pro")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
    print("[Stripe] ⚠️ No se ha encontrado ninguna clave secreta de Stripe en las variables de entorno.")
    # No rompemos el import: el error saldrá al intentar crear sesión si se usa sin configurar.


# ======================================================
# 1) Crear sesión de checkout (Galenos PRO)
#    - SIN autenticación obligatoria (como anoche)
#    - email OPCIONAL (si viene, lo usamos; si no, Stripe lo pide)
# ======================================================
@router.get("/create-checkout-session")
async def create_checkout_session(
    email: Optional[str] = Query(
        None,
        description="Correo del médico (opcional; si se envía, se utiliza como customer_email en Stripe).",
    ),
):
    """Crea una sesión de checkout para Galenos PRO.

    Punto importante:
    - No exige token JWT (se puede llamar desde la landing o alta libre).
    - No exige `email` en la URL; se puede omitir.
    - No lanza errores "de configuración" si las variables existen con nombres antiguos
      porque intentamos varias combinaciones arriba.
    """

    # Comprobación suave: solo avisamos si falta ALGO crítico.
    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        print(
            "[Stripe] ❌ create-checkout-session llamado sin STRIPE_SECRET_KEY o STRIPE_PRICE_ID configurados."
        )
        # En lugar de inventarnos un mensaje, devolvemos 500 genérico para que el front enseñe el texto suyo.
        raise HTTPException(status_code=500, detail="Error interno al iniciar el pago en Stripe.")

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
            allow_promotion_codes=True,
            subscription_data={
                # Puedes ajustar los días de prueba si lo deseas.
                "trial_period_days": 3,
            },
            # Si pasamos email, Stripe pre-rellena el formulario; si no, simplemente lo pide al usuario.
            customer_email=email,
            success_url=f"{FRONTEND_URL}/panel-medico?checkout=success",
            cancel_url=f"{FRONTEND_URL}/panel-medico?checkout=cancel",
            metadata={
                "app": "galenos.pro",
                "source": "create-checkout-session",
                "email": email or "",
            },
        )

        print(f"[Stripe] ✅ Sesión de checkout creada correctamente. ID: {session.id}")
        return {"checkout_url": session.url}

    except Exception as e:
        print("[Stripe] ❌ Error al crear sesión de checkout:", repr(e))
        raise HTTPException(
            status_code=500,
            detail="No se ha podido iniciar el pago en Stripe.",
        )


# ======================================================
# 2) Webhook de Stripe
#    - Activa PRO cuando se completa el checkout
# ======================================================
@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Webhook de Stripe para eventos importantes (de momento:
    - checkout.session.completed → activamos PRO para el médico.
    """

    if not STRIPE_WEBHOOK_SECRET:
        print("[Stripe] ⚠️ Webhook llamado sin STRIPE_WEBHOOK_SECRET configurado.")
        raise HTTPException(status_code=500, detail="Stripe webhook no está configurado en el backend.")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        print("[Stripe] ❌ Payload inválido en webhook.")
        raise HTTPException(status_code=400, detail="Payload inválido")
    except stripe.error.SignatureVerificationError:
        print("[Stripe] ❌ Firma inválida en webhook.")
        raise HTTPException(status_code=400, detail="Firma inválida")

    event_type = event.get("type")
    data_object = event.get("data", {}).get("object", {})

    print(f"[Stripe] 📩 Evento recibido: {event_type}")

    if event_type == "checkout.session.completed":
        # email puede venir en customer_details o en customer_email
        customer_email = (
            (data_object.get("customer_details") or {}).get("email")
            or data_object.get("customer_email")
        )
        subscription_id = data_object.get("subscription")
        customer_id = data_object.get("customer")

        print(f"[Stripe] ✅ checkout.session.completed para {customer_email}")

        # Intentamos sacar trial_end de la suscripción (si existe)
        trial_end_dt = None
        if subscription_id:
            try:
                sub = stripe.Subscription.retrieve(subscription_id)
                if sub and getattr(sub, "trial_end", None):
                    trial_end_dt = datetime.utcfromtimestamp(sub.trial_end)
            except Exception as e:
                print("[Stripe] ⚠️ No se pudo recuperar la suscripción para trial_end:", repr(e))

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
                print(f"[Stripe] ⚠️ No se encontró ningún usuario con email {customer_email}")
        else:
            print("[Stripe] ⚠️ checkout.session.completed sin email de cliente.")

    # Otros eventos (cancelaciones, etc.) se pueden manejar aquí más adelante.
    return JSONResponse({"received": True})
