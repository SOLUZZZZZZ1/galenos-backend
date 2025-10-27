# galenos.pro – Backend (FastAPI)

## Instalación
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Endpoints
- GET /health → status
- POST /auth/register → registro simulado
- POST /uploads → subir informe PDF (devuelve demo de extracción)
- POST /stripe/webhook → stub

## Entorno (.env)
- STORAGE_DIR=./storage
- CORS_ORIGINS=http://localhost:5173
- STRIPE_SECRET_KEY=sk_test_xxx
- STRIPE_WEBHOOK_SECRET=whsec_xxx
