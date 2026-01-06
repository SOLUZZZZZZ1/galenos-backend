# medical_news_router.py — Actualidad médica (RSS en directo + cache BD)
# Endpoints:
# - GET /medical-news/live?limit=20&days=15  -> RSS en directo; si falla, fallback a BD
# - GET /medical-news?limit=50              -> últimos items guardados en BD
# - POST /medical-news/seed-demo            -> inserta 1 demo en BD

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import re

import feedparser
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from models import MedicalNews
from schemas import MedicalNewsReturn

router = APIRouter(prefix="/medical-news", tags=["medical-news"])

SOURCES = [
    {"name": "WHO · News Releases", "url": "https://www.who.int/rss-feeds/news-english.xml"},
    {"name": "NIH · News Releases", "url": "https://www.nih.gov/news/feed.xml"},
    {"name": "CDC · Media Releases", "url": "https://tools.cdc.gov/api/v2/resources/media/132608.rss"},
    {"name": "CDC · Media Releases (Alt)", "url": "https://tools.cdc.gov/api/v2/resources/media/403372.rss"},
    {"name": "CDC · Emerging Infectious Diseases (Ahead of Print)", "url": "http://wwwnc.cdc.gov/eid/rss/ahead-of-print.xml"},
    {"name": "BMJ · Latest News", "url": "https://www.bmj.com/rss/news.xml"},
]

USER_AGENT = "GalenosBot/1.0 (+https://galenos.pro)"
RECENCY_DAYS = 15

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_text(s: str) -> str:
    if not s:
        return ""
    s = _TAG_RE.sub(" ", s)
    s = s.replace("&nbsp;", " ")
    s = _WS_RE.sub(" ", s).strip()
    return s


def _to_dt(entry: Dict[str, Any]) -> Optional[datetime]:
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    if not st:
        return None
    try:
        return datetime(*st[:6], tzinfo=timezone.utc)
    except Exception:
        return None


def _extract_summary(entry: Dict[str, Any]) -> str:
    s = entry.get("summary") or ""
    if not s and isinstance(entry.get("summary_detail"), dict):
        s = entry["summary_detail"].get("value") or ""
    if not s:
        s = entry.get("description") or ""
    return _clean_text(s)[:800]


def _guess_tags(title: str, summary: str) -> str:
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
    tags = list(dict.fromkeys(tags))
    return ",".join(tags)


def _fetch_feed(url: str) -> feedparser.FeedParserDict:
    return feedparser.parse(url, request_headers={"User-Agent": USER_AGENT})


def _save_items_to_db(db: Session, items: List[Dict[str, Any]], max_save: int = 40) -> int:
    """
    Guarda items en BD como cache.
    Evita duplicados por source_url (best effort).
    """
    saved = 0
    for it in (items or [])[:max_save]:
        url = (it.get("source_url") or "").strip()
        title = (it.get("title") or "").strip()
        if not url or not title:
            continue

        exists = db.query(MedicalNews).filter(MedicalNews.source_url == url).first()
        if exists:
            continue

        row = MedicalNews(
            title=title,
            summary=it.get("summary") or "",
            source_name=it.get("source_name") or "RSS",
            source_url=url,
            published_at=it.get("published_at"),
            specialty_tags=it.get("specialty_tags") or "general",
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        saved += 1

    if saved:
        db.commit()
    return saved


def _fallback_from_db(db: Session, limit: int) -> List[Dict[str, Any]]:
    rows = (
        db.query(MedicalNews)
        .order_by(MedicalNews.published_at.desc().nullslast(), MedicalNews.id.desc())
        .limit(limit)
        .all()
    )
    out: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for r in rows:
        out.append(
            {
                "id": getattr(r, "id", 0) or 0,
                "title": r.title,
                "summary": r.summary,
                "source_name": r.source_name,
                "source_url": r.source_url,
                "published_at": r.published_at,
                "specialty_tags": getattr(r, "specialty_tags", None),
                "created_at": getattr(r, "created_at", None) or now,
                "cached": True,
            }
        )
    return out


@router.get("/live")
def live_news(
    limit: int = Query(20, ge=1, le=60),
    days: int = Query(RECENCY_DAYS, ge=1, le=60),
    db: Session = Depends(get_db),
):
    items: List[Dict[str, Any]] = []
    seen_urls = set()

    # 1) Intento LIVE
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
                        "id": 0,
                        "title": title or "Sin título",
                        "summary": summary,
                        "source_name": src["name"],
                        "source_url": url,
                        "published_at": published_at,
                        "specialty_tags": _guess_tags(title, summary),
                        "created_at": datetime.now(timezone.utc),
                        "cached": False,
                    }
                )
                seen_urls.add(url)
        except Exception:
            continue

    # 2) Filtro “blando” de recencia
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    filtered: List[Dict[str, Any]] = []
    for it in items:
        pub = it.get("published_at")
        if pub is not None and pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)

        # Si hay fecha y es muy vieja -> fuera. Si no hay fecha -> se queda.
        if pub is not None and pub < cutoff:
            continue
        filtered.append(it)

    items = filtered

    # 3) Orden
    def sort_key(x):
        return x.get("published_at") or x.get("created_at") or datetime(1970, 1, 1, tzinfo=timezone.utc)

    items.sort(key=sort_key, reverse=True)

    # 4) Si LIVE trae algo -> guardar cache y devolver
    if items:
        try:
            _save_items_to_db(db, items, max_save=40)
        except Exception:
            # si falla cache, no rompemos live
            pass
        return {"generated_at": now, "items": items[:limit], "mode": "live"}

    # 5) Si LIVE no trae nada -> fallback a BD
    cached = _fallback_from_db(db, limit)
    if cached:
        return {"generated_at": now, "items": cached, "mode": "cache"}

    # 6) Si tampoco hay cache -> vacío (pero ya sabrás que es “sin cache aún”)
    return {"generated_at": now, "items": [], "mode": "empty"}


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
