# imaging.py — Endpoints para TAC/RM/RX/ECO reales

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
from auth import get_current_user
from database import get_db
from openai import OpenAI
import base64
from utils_imagen import analyze_medical_image
from prompts_imagen import SYSTEM_PROMPT_IMAGEN
import crud
from schemas import ImagingReturn

router = APIRouter(prefix="/imaging", tags=["Imaging"])

client = OpenAI()


@router.post("/upload", response_model=ImagingReturn)
async def upload_imaging(
    patient_id: int = Form(...),
    img_type: str = Form("imagen"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    patient = crud.get_patient_by_id(db, patient_id, current_user.id)
    if not patient:
        raise HTTPException(404, "Paciente no encontrado.")

    content = await file.read()
    img_b64 = base64.b64encode(content).decode()

    # IA Vision
    summary, differential, patterns = analyze_medical_image(
        client=client,
        image_b64=img_b64,
        model="gpt-4o",
        system_prompt=SYSTEM_PROMPT_IMAGEN
    )

    # Guardar en BD
    imaging = crud.create_imaging(
        db=db,
        patient_id=patient.id,
        img_type=img_type,
        summary=summary,
        differential=differential,
        file_path=None
    )

    crud.add_patterns_to_imaging(db, imaging.id, patterns)

    return imaging
