# app.py — Backend mínimo Galenos.pro (FastAPI + IA listo para conectar)
import os
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(
    title="Galenos.pro API",
    description="Backend base para Galenos.pro (panel de apoyo a médicos).",
    version="0.1.0",
)

# MODELOS BÁSICOS PARA PROBAR

class PingOut(BaseModel):
    ok: bool
    message: str
    version: str

@app.get("/ping", response_model=PingOut)
def ping():
    return PingOut(ok=True, message="Galenos.pro backend vivo", version="0.1.0")
