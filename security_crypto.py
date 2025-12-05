# security_crypto.py — Cifrado AES (Fernet) para Galenos
#
# Requiere:
#   DATA_ENCRYPTION_KEY=<clave generada con Fernet.generate_key().decode()>
#
# AES-256 + HMAC con Fernet
# Compatibilidad total con datos antiguos SIN cifrar.

import os
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

KEY = os.getenv("DATA_ENCRYPTION_KEY")

if not KEY:
    raise RuntimeError(
        "DATA_ENCRYPTION_KEY no está configurada. "
        "Genera una clave con: from cryptography.fernet import Fernet; Fernet.generate_key().decode()"
    )

if isinstance(KEY, str):
    KEY = KEY.encode()

fernet = Fernet(KEY)


def encrypt_text(plaintext: Optional[str]) -> Optional[str]:
    if plaintext is None:
        return None
    if not isinstance(plaintext, str):
        plaintext = str(plaintext)
    token = fernet.encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_text(ciphertext: Optional[str]) -> Optional[str]:
    if ciphertext is None:
        return None

    # Datos antiguos → retornar tal cual
    if len(ciphertext) < 30:
        return ciphertext

    try:
        data = fernet.decrypt(ciphertext.encode("utf-8"))
        return data.decode("utf-8")
    except InvalidToken:
        return ciphertext
    except Exception:
        return ciphertext
