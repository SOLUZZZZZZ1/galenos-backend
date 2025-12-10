from typing import List, Optional
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

    Más adelante se puede conectar a un servicio que alimente la tabla medical_news
    desde RSS/APIs externas con resúmenes automáticos.
    """
    if limit <= 0 or limit > 100:
        raise HTTPException(status_code=400, detail="El parámetro 'limit' debe estar entre 1 y 100.")

    q = db.query(MedicalNews)

    if specialty:
        # Búsqueda sencilla por substring en specialty_tags, p.ej. "cardio,urgencias"
        like_val = f"%{specialty.lower()}%"
        q = q.filter(MedicalNews.specialty_tags.ilike(like_val))

    q = q.order_by(
        MedicalNews.published_at.desc().nullslast(),
        MedicalNews.created_at.desc(),
    )

    return q.limit(limit).all()
