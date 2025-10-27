from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os, uuid, shutil

app = FastAPI(title="galenos.pro API", version="0.1.0")

CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STORAGE_DIR = os.environ.get("STORAGE_DIR", "./storage")
os.makedirs(STORAGE_DIR, exist_ok=True)

class RegisterIn(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: str
    country: Optional[str] = "ES"
    license_number: Optional[str] = None

class RegisterOut(BaseModel):
    user_id: str
    message: str

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/auth/register", response_model=RegisterOut)
async def register(payload: RegisterIn):
    fake_user_id = str(uuid.uuid4())
    return {"user_id": fake_user_id, "message": "Registered (stub). Connect DB + Stripe in production."}

@app.post("/uploads")
async def upload_report(file: UploadFile = File(...), patient_alias: str = Form(...)):
    if not file.filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")):
        raise HTTPException(status_code=400, detail="Only PDF/PNG/JPG allowed.")
    report_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1]
    dest_path = os.path.join(STORAGE_DIR, f"{report_id}{ext}")
    with open(dest_path, "wb") as out:
        shutil.copyfileobj(file.file, out)
    extraction = {
        "patient_alias": patient_alias,
        "file_id": report_id,
        "markers": [
            {"name": "Glucose", "value": 102, "unit": "mg/dL", "ref_min": 70, "ref_max": 100},
            {"name": "LDL Cholesterol", "value": 142, "unit": "mg/dL", "ref_min": 0, "ref_max": 130},
            {"name": "TSH", "value": 3.2, "unit": "µIU/mL", "ref_min": 0.27, "ref_max": 4.2},
        ]
    }
    return {"ok": True, "file_path": dest_path, "extraction": extraction}

@app.post("/stripe/webhook")
async def stripe_webhook():
    return {"received": True}
