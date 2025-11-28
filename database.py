# database.py — Conexión a PostgreSQL para Galenos.pro

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# Obtiene la URL desde Render (DATABASE_URL)
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("❌ No se ha definido DATABASE_URL en las variables de entorno.")

# Conexión al motor
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


# Dependencia para FastAPI (inyección de sesiones)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
