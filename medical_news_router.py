# medical_news_router.py — Actualidad médica Galenos
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import MedicalNews
from schemas import MedicalNewsReturn

router = APIRouter(prefix="/medical-news", tags=["medical-news"])


@router.get("/", response_model=List[MedicalNewsReturn])
def list_medical_news(
    db: Session = Depends(get_db),
    specialty: Optional[str] = None,
    limit: int = 20,
):
    """
    Devuelve un listado de noticias médicas resumidas.

    - specialty: filtro opcional por etiqueta de especialidad (ej: "cardio", "urgencias").
    - limit: máximo de noticias a devolver.
    """
    if limit <= 0 or limit > 100:
        raise HTTPException(
            status_code=400,
            detail="El parámetro 'limit' debe estar entre 1 y 100.",
        )

    q = db.query(MedicalNews)

    if specialty:
        like_val = f"%{specialty.lower()}%"
        q = q.filter(MedicalNews.specialty_tags.ilike(like_val))

    q = q.order_by(
        MedicalNews.published_at.desc().nullslast(),
        MedicalNews.created_at.desc(),
    )

    return q.limit(limit).all()


@router.post("/admin-demo", response_model=MedicalNewsReturn)
def create_demo_news(db: Session = Depends(get_db)):
    """
    Crea una noticia de ejemplo en medical_news para probar la sección
    de Actualidad médica.

    Solo para uso interno / pruebas. En producción real, esto se sustituye
    por el servicio RSS o inserciones reales.
    """
    demo = MedicalNews(
        title="Ejemplo de noticia clínica en Galenos",
        summary=(
            "Esta es una noticia de ejemplo para comprobar la sección de "
            "Actualidad médica. En producción, aquí verás resúmenes reales "
            "de estudios, guías clínicas o alertas sanitarias."
        ),
        source_name="Galenos · Demo interna",
        source_url="https://galenos.pro/",
        published_at=datetime.utcnow(),
        specialty_tags="general",
        created_at=datetime.utcnow(),
    )
    db.add(demo)
    db.commit()
    db.refresh(demo)
    return demo
