# moderation_utils.py — STRONG (Galenos)
# Moderación determinista reforzada para De Guardia / Comunidad (entorno clínico)

import re
import unicodedata

def normalize_text(text: str) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", text.strip())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"(.)\1{2,}", r"\1", t)  # iiiidiota -> idiota
    t = re.sub(r"[^a-zA-Z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.lower().strip()

# Insultos (tokens simples)
INSULT_TOKENS = {
    "idiota","imbecil","gilipollas","subnormal","estupido","tonto","payaso","inutil",
    "mierda","asco","cretino","capullo","cabron","mierdas"
}

# Insultos compuestos / frases
INSULT_PATTERNS = [
    r"\bhijo\s+de\s+puta\b",
    r"\bputa\b",
    r"\bputo\s+\w+\b",
    r"\bde\s+mierda\b",
    r"\bmaldito\s+\w+\b",
    r"\bque\s+te\s+den\b",
    r"\bme\s+cago\s+en\b",
    r"\bimbecil\s+de\s+\w+\b",
]

# Política / ideología (tolerancia cero)
POLITICS_PATTERNS = [
    r"\bgobierno\b",
    r"\bpolitic[oa]s?\b",
    r"\bfascis\w*\b",
    r"\bcomunis\w*\b",
    r"\broj[oa]s?\b",
    r"\bfach[ao]s?\b",
    r"\bprogre\w*\b",
    r"\bultraderech\w*\b",
    r"\bizquierd\w*\b",
    r"\bderech\w*\b",
    r"\bvox\b",
    r"\bpp\b",
    r"\bpsoe\b",
]

# Prevee PII (review -> aquí bloqueamos en De Guardia por defecto)
PII_PATTERNS = [
    r"\b\d{8}[a-zA-Z]\b",  # DNI
    r"\b\d{9}\b",          # teléfono
    r"\bcalle\s+\w+",
    r"\bavenida\s+\w+",
    r"\bpasaporte\b",
    r"\bemail\b",
]

def moderate_text_strong(text: str):
    t = normalize_text(text)
    if not t:
        return "block", "Mensaje vacío."
    for pat in INSULT_PATTERNS:
        if re.search(pat, t):
            return "block", "Lenguaje no profesional."
    for pat in POLITICS_PATTERNS:
        if re.search(pat, t):
            return "block", "Contenido político o ideológico no permitido."
    tokens = set(t.split())
    if tokens & INSULT_TOKENS:
        return "block", "Lenguaje no profesional."
    for pat in PII_PATTERNS:
        if re.search(pat, t):
            return "review", "Posible dato personal o identificable. Elimina datos y vuelve a enviar."
    return "allow", "OK"

# Compatibilidad: si en algún punto se importa quick_block_reason
def quick_block_reason(text: str):
    action, reason = moderate_text_strong(text)
    return (action != "allow"), reason
