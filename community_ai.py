# community_ai.py — IA para resumen del concurso semanal

import os
from fastapi import HTTPException
from openai import OpenAI

from prompts_community import COMMUNITY_SUMMARY_PROMPT


def generate_community_summary(full_case_text: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY") or ""
    if not api_key:
        raise HTTPException(500, "Falta OPENAI_API_KEY en el servidor.")

    client = OpenAI(api_key=api_key)

    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL") or "gpt-4.1-mini",
        messages=[
            {"role": "system", "content": COMMUNITY_SUMMARY_PROMPT.strip()},
            {"role": "user", "content": full_case_text.strip()},
        ],
        temperature=0.2,
    )

    txt = (resp.choices[0].message.content or "").strip()
    if not txt:
        raise HTTPException(500, "La IA no devolvió contenido.")
    return txt
