# medical_news_router.py — Actualidad médica (RSS en directo estilo Mediazion)
from typing import List, Optional, Dict, Any
from datetime import datetime
import re

import feedparser
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import MedicalNews
from schemas import MedicalNewsReturn

router = APIRouter(prefix="/medical-news", tags=["medical-news"])


# ===========================
# RSS MÉDICOS (en directo)
# ===========================
RSS_SOURCES = [
    # PubMed "breaking"/recientes (feed general de búsqueda: ajustable)
    {
        "name": "PubMed",
        "url": "https://pubmed.ncbi.nlm.nih.gov/rss/search/1pEJQqybNgFPzZAjq9uGUFERScv3P4Zv3hPHAgKgdv3o2QoqwU/?limit=25&utm_campaign=pubmed-2&fc=20231206022115",
    },
    # WHO news
    {
        "name": "WHO News",
        "url": "https://www.who.int/rss-feeds/news-english.xml",
    },
    # CDC (press releases)
    {
        "name": "CDC Press Releases",
        "url": "https://tools.cdc.gov/api/v2/resources/media/132608.rss",
    },
    # NICE (news)
    {
        "name": "NICE News",
        "url": "https://www.nice.org.uk/News-RSS",
    },
]


def _safe_text(x: Any) -> str:
    return (str(x) if x is not None else "").strip()


def _clean_html(text: str) -> str:
    # Limpieza mínima para resúmenes RSS
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_date(entry: Dict[str, Any]) -> Optional[datetime]:
    # feedparser da published_parsed / updated_parsed con struct_time
    try:
        if entry.get("published_parsed"):
            import time
            return datetime.fromtimestamp(time.mktime(entry["published_parsed"]))
        if entry.get("updated_parsed"):
            import time
            return datetime.fromtimestamp(time.mktime(entry["updated_parsed"]))
    except Exception:
        return None
    return None


@router.get("/live")
def live_medical_news(
    q: Optional[str] = None,
    limit: int = 20,
):
    """
    Devuelve noticias médicas en DIRECTO desde RSS (sin BD).
    - q: filtro opcional por texto (título/resumen/fuente)
    - limit: máximo de elementos
    """
    if limit <= 0:
        limit = 20
    if limit > 50:
        limit = 50

    q_norm = _safe_text(q).lower()
    items: List[Dict[str, Any]] = []

    for src in RSS_SOURCES:
        feed = feedparser.parse(
    src["url"],
    request_headers={"User-Agent": "GalenosBot/1.0 (+https://galenos.pro)"}
)

            published_at = None
            try:
                published_at = _parse_date(e)
            except Exception:
                published_at = None

            item = {
                "title": title,
                "summary": summary[:280] if summary else "",
                "source_name": src["name"],
                "source_url": link or src["url"],
                "published_at": published_at.isoformat() if published_at else None,
            }

            # filtro q
            if q_norm:
                haystack = f"{item['title']} {item['summary']} {item['source_name']}".lower()
                if q_norm not in haystack:
                    continue

            # evitar duplicados por url
            if item["source_url"] and any(it["source_url"] == item["source_url"] for it in items):
                continue

            items.append(item)

    # ordenar por fecha (si la hay) y por aparición
    def sort_key(it):
        dt = it.get("published_at")
        return dt or ""

    items.sort(key=sort_key, reverse=True)
    return {"items": items[:limit], "sources": [s["name"] for s in RSS_SOURCES]}


# ===========================
# BD (opcional)
# ===========================
@router.get("/", response_model=List[MedicalNewsReturn])
def list_medical_news_db(
    db: Session = Depends(get_db),
    limit: int = 20,
):
    """
    Devuelve noticias guardadas en BD (si usas tabla medical_news).
    """
    if limit <= 0:
        limit = 20
    if limit > 100:
        limit = 100

    q = db.query(MedicalNews).order_by(
        MedicalNews.published_at.desc().nullslast(),
        MedicalNews.created_at.desc(),
    )
    return q.limit(limit).all()


@router.get("/admin-demo", response_model=MedicalNewsReturn)
def create_demo_news(db: Session = Depends(get_db)):
    """
    Inserta una noticia demo en BD.
    """
    demo = MedicalNews(
        title="Ejemplo de noticia clínica en Galenos",
        summary="Noticia demo para probar la pestaña Actualidad médica.",
        source_name="Galenos · Demo",
        source_url="https://galenos.pro/",
        published_at=datetime.utcnow(),
        specialty_tags="general",
        created_at=datetime.utcnow(),
    )
    db.add(demo)
    db.commit()
    db.refresh(demo)
    return demo
