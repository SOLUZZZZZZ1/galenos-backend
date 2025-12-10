import time
import logging
from datetime import datetime
from typing import Optional

import feedparser
from sqlalchemy.orm import Session

from database import SessionLocal
from models import MedicalNews

# ---------------------------------------------------------
# Servicio sencillo de RSS para Galenos
#
# - Lee un feed RSS cada X segundos
# - Extrae la última noticia
# - Si no existe en medical_news (por source_url), la inserta
#
# Puedes arrancarlo con:
#    python rss_news_worker.py
#
# Y dejarlo corriendo en segundo plano junto al backend.
# ---------------------------------------------------------

# RSS de ejemplo (modificable):
# Puedes cambiar este URL por el feed que prefieras.
RSS_URL = "https://pubmed.ncbi.nlm.nih.gov/rss/search/1pEJQqybNgFPzZAjq9uGUFERScv3P4Zv3hPHAgKgdv3o2QoqwU/?limit=10&utm_campaign=pubmed-2&fc=20231206022115"
CHECK_INTERVAL_SECONDS = 600  # cada 10 minutos


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [RSS] %(levelname)s: %(message)s",
)


def get_db() -> Session:
    """Crea una sesión nueva de BD (igual patrón que en FastAPI)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def find_news_by_url(db: Session, url: str) -> Optional[MedicalNews]:
    return db.query(MedicalNews).filter(MedicalNews.source_url == url).first()


def insert_news_from_entry(db: Session, entry) -> Optional[MedicalNews]:
    """Convierte una entrada de RSS en un registro de MedicalNews."""
    link = getattr(entry, "link", None)
    title = getattr(entry, "title", "").strip() if getattr(entry, "title", None) else ""
    summary = getattr(entry, "summary", "").strip() if getattr(entry, "summary", None) else ""

    if not link or not title:
        return None

    # ¿Ya existe?
    existing = find_news_by_url(db, link)
    if existing:
        return None

    # Intentar obtener fecha de publicación
    published_at = None
    if getattr(entry, "published_parsed", None):
        try:
            import time as _time
            published_at = datetime.fromtimestamp(
                _time.mktime(entry.published_parsed)
            )
        except Exception:
            published_at = None

    news = MedicalNews(
        title=title,
        summary=summary,
        source_name="PubMed (RSS)",
        source_url=link,
        published_at=published_at,
        specialty_tags="general",  # podrás refinarlo más adelante
        created_at=datetime.utcnow(),
    )
    db.add(news)
    db.commit()
    db.refresh(news)
    return news


def process_feed_once():
    """Lee el RSS una vez e intenta añadir al menos una noticia nueva."""
    logging.info(f"Leyendo RSS: {RSS_URL}")
    feed = feedparser.parse(RSS_URL)

    if getattr(feed, "bozo", 0):
        logging.error(f"Error al leer el feed RSS: {getattr(feed, 'bozo_exception', 'desconocido')}")
        return

    entries = getattr(feed, "entries", [])
    if not entries:
        logging.info("El feed RSS no devuelve entradas.")
        return

    inserted_count = 0
    db = SessionLocal()
    try:
        for entry in entries:
            news = insert_news_from_entry(db, entry)
            if news:
                inserted_count += 1
                logging.info(f"Nueva noticia guardada: {news.title}")
                break
    finally:
        db.close()

    if inserted_count == 0:
        logging.info("No se han encontrado noticias nuevas en esta pasada.")


def main_loop():
    logging.info("Servicio RSS de Actualidad Médica iniciado.")
    logging.info(f"Comprobando el feed cada {CHECK_INTERVAL_SECONDS} segundos.")
    while True:
        try:
            process_feed_once()
        except Exception as e:
            logging.exception(f"Error procesando el feed RSS: {e}")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main_loop()
