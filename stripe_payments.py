# stripe_payments.py — Integración Stripe para Galenos.pro
import os
import stripe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

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
async def create_checkout_session():
    """
    Crea una sesión de Checkout para Galenos PRO (10 €/mes, 3 días de prueba).
    Devuelve una URL de Stripe para redirigir al usuario.
    """
    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        raise HTTPException(
            status_code=500,
            detail="Stripe no está configurado correctamente en el backend.",
        )

    try:
        # Email demo por ahora; más adelante se puede sacar del usuario autenticado
        fake_email = "doctor-demo@galenos.pro"

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
            customer_email=fake_email,
            metadata={"app": "galenos.pro"},
        )

        return {"checkout_url": session.url}

    except Exception as e:
        print("[Stripe] Error creando sesión de checkout:", repr(e))
        raise HTTPException(
            status_code=500,
            detail="No se ha podido iniciar el pago en Stripe.",
        )


# ======================================================
# Endpoint: webhook de Stripe
# ======================================================
@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request):
    """
    Webhook de Stripe:
    - Verifica la firma con STRIPE_WEBHOOK_SECRET.
    - Maneja eventos importantes (de momento solo checkout.session.completed).
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
        raise HTTPException(status_code=400, detail="Firma inválida"

        )

    event_type = event.get("type")
    data_object = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        customer_email = (
            (data_object.get("customer_details") or {}).get("email") or
            data_object.get("customer_email")
        )

        # TODO: aquí es donde puedes marcar al médico como PRO en la BD.
        # 1. Buscar usuario por email en la tabla User.
        # 2. Actualizar campo (ej: user.is_pro = True / user.plan = "PRO").
        # 3. Guardar cambios.
        #
        # Lo dejamos como print para no tocar tu modelo actual.
        print(f"[Stripe] ✅ checkout.session.completed para {customer_email}")

    # Aquí podrías manejar otros eventos: invoice.paid, customer.subscription.deleted, etc.
    # De momento los ignoramos y solo confirmamos recepción.
    return JSONResponse({"received": True})
