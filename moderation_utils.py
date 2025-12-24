# moderation_utils.py — Capa 1 (determinista) · Galenos (STRICT)
# Bloqueo inmediato de insultos/política/PII.
import re
import unicodedata
from typing import Tuple

INSULT_TOKENS = {
    "idiota","imbecil","imbécil","estupido","estúpido","gilipollas","subnormal",
    "capullo","payaso","mierda","puta","tonto","tonta","imbeciles","imbéciles"
}

POLITICS_TOKENS = {
    "psoe","pp","vox","podemos","sumar","ciudadanos","erc","bildu","junts",
    "izquierda","derecha","fascista","comunista","socialista","liberal",
    "presidente","gobierno","ministro","congreso","senado","elecciones","votar","campaña",
    "religion","religión","iglesia","allah","dios"
}

PII_PATTERNS = [
    r"\b\d{8}[A-Za-z]\b",
    r"\b\+?\d{9,14}\b",
    r"\b(calle|av\.?|avenida|plaza|paseo)\b",
    r"\b(nº|no\.?)\s*\d+\b",
]

def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", (text or "").strip())

def _tokenize(text: str) -> set[str]:
    t = _normalize(text).lower()
    t = re.sub(r"[^\wáéíóúüñ]+", " ", t, flags=re.IGNORECASE)
    return {x for x in t.split() if x}

def quick_block_reason(text: str) -> Tuple[bool, str]:
    if not (text or "").strip():
        return True, "Mensaje vacío."

    tokens = _tokenize(text)

    if tokens & INSULT_TOKENS:
        return True, "Lenguaje no profesional."

    if tokens & POLITICS_TOKENS:
        return True, "Contenido político/ideológico no permitido en De Guardia."

    t = _normalize(text)
    for pat in PII_PATTERNS:
        if re.search(pat, t, flags=re.IGNORECASE):
            return True, "Posibles datos identificativos. Elimina información personal."

    return False, ""
