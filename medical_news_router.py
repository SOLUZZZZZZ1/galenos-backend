# medical_news_router.py — Actualidad médica (RSS en directo)
# Endpoints:
# - GET /medical-news/live?limit=20  -> RSS en directo (NO guarda en BD)
# - GET /medical-news?limit=50       -> últimos items guardados en BD (si los usas)
# - POST /medical-news/seed-demo     -> inserta 1 demo en BD

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import re

import feedparser
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from models import MedicalNews
from schemas import MedicalNewsReturn

router = APIRouter(prefix="/medical-news", tags=["medical-news"])

# -----------------------------------------
# FUENTES RSS (sin SciAm, como me has pedido)
# -----------------------------------------
SOURCES = [
    {"name": "WHO · News Releases", "url": "https://www.who.int/rss-feeds/news-english.xml"},
    {"name": "CDC · Newsroom", "url": "https://tools.cdc.gov/api/v2/resources/media/403372.rss"},
    {"name": "NIH · News Releases", "url": "https://www.nih.gov/news-events/news-releases/rss.xml"},
    {"name": "NICE · News", "url": "https://www.nice.org.uk/rss/news.xml"},
    {"name": "ECDC · News", "url": "https://www.ecdc.europa.eu/en/news-events/feed"},
    {"name": "BMJ · Latest News", "url": "https://www.bmj.com/rss/news.xml"},
]

USER_AGENT = "GalenosBot/1.0 (+https://galenos.pro)"

# -----------------------------------------
# Helpers
# -----------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_text(s: str) -> str:
    if not s:
        return ""
    s = _TAG_RE.sub(" ", s)          # quita HTML
    s = s.replace("&nbsp;", " ")
    s = _WS_RE.sub(" ", s).strip()   # normaliza espacios
    return s


def _to_dt(entry: Dict[str, Any]) -> Optional[datetime]:
    """
    Convierte published_parsed / updated_parsed a datetime UTC, si existe.
    """
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    if not st:
        return None
    try:
        dt = datetime(*st[:6], tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _extract_summary(entry: Dict[str, Any]) -> str:
    # feedparser suele traer summary, summary_detail.value o description
    s = entry.get("summary") or ""
    if not s and isinstance(entry.get("summary_detail"), dict):
        s = entry["summary_detail"].get("value") or ""
    if not s:
        s = entry.get("description") or ""
    return _clean_text(s)[:800]  # recorte razonable


def _guess_tags(title: str, summary: str) -> str:
    """
    Tags simples (no críticos). Puedes ampliarlo luego.
    """
    t = (title + " " + summary).lower()

    tags = []
    if any(k in t for k in ["cardio", "heart", "miocard", "infarto", "arrhythm", "atrial"]):
        tags.append("cardiología")
    if any(k in t for k in ["pulmon", "respir", "asthma", "copd", "neumo", "pneum"]):
        tags.append("neumología")
    if any(k in t for k in ["cancer", "oncolog", "tumor", "chemo"]):
        tags.append("oncología")
    if any(k in t for k in ["stroke", "ictus", "neuro", "alzheimer", "parkinson"]):
        tags.append("neurología")
    if any(k in t for k in ["infection", "infect", "virus", "bacteria", "covid", "influenza"]):
        tags.append("infecciosas")
    if any(k in t for k in ["diabetes", "glucose", "insulin", "obesity", "metabolic"]):
        tags.append("endocrino")
    if any(k in t for k in ["trial", "study", "research", "randomized", "meta-analysis"]):
        tags.append("investigación")

    if not tags:
        tags.append("general")

    # sin duplicados
    tags = list(dict.fromkeys(tags))
    return ",".join(tags)


def _fetch_feed(url: str) -> feedparser.FeedParserDict:
    # Importante: algunos RSS “callan” si no envías User-Agent
    return feedparser.parse(url, request_headers={"User-Agent": USER_AGENT})


# -----------------------------------------
# LIVE: RSS en directo (sin BD)
# -----------------------------------------
@router.get("/live")
def live_news(
    limit: int = Query(20, ge=1, le=60),
):
    items: List[Dict[str, Any]] = []
    seen_urls = set()

    for src in SOURCES:
        try:
            feed = _fetch_feed(src["url"])
            entries = getattr(feed, "entries", []) or []

            for e in entries[:25]:
                url = (e.get("link") or "").strip()
                title = _clean_text((e.get("title") or "").strip())

                if not url or url in seen_urls:
                    continue

                published_at = _to_dt(e)
                summary = _extract_summary(e)

                items.append(
                    {
                        "id": 0,  # live no usa BD
                        "title": title or "Sin título",
                        "summary": summary,
                        "source_name": src["name"],
                        "source_url": url,
                        "published_at": published_at,
                        "specialty_tags": _guess_tags(title, summary),
                        "created_at": datetime.now(timezone.utc),
                    }
                )
                seen_urls.add(url)

        except Exception:
            # si una fuente falla, no rompe todo el feed
            continue

    # Ordena: más reciente primero. Si no hay fecha, al final.
    def sort_key(x):
        dt = x.get("published_at")
        return dt or datetime(1970, 1, 1, tzinfo=timezone.utc)

    items.sort(key=sort_key, reverse=True)
    return {"items": items[:limit]}


# -----------------------------------------
# BD: listado guardado (si lo usas)
# -----------------------------------------
@router.get("", response_model=List[MedicalNewsReturn])
def list_news_db(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(MedicalNews)
        .order_by(MedicalNews.published_at.desc().nullslast(), MedicalNews.id.desc())
        .limit(limit)
        .all()
    )
    return rows


@router.post("/seed-demo", response_model=MedicalNewsReturn)
def seed_demo(db: Session = Depends(get_db)):
    demo = MedicalNews(
        title="Ejemplo de noticia clínica en Galenos",
        summary="Noticia demo para probar la pestaña Actualidad médica.",
        source_name="Galenos · Demo",
        source_url="https://galenos.pro/",
        published_at=datetime.now(timezone.utc),
        specialty_tags="general",
        created_at=datetime.now(timezone.utc),
    )
    db.add(demo)
    db.commit()
    db.refresh(demo)
    return demo
