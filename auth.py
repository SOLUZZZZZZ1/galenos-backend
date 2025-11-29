import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
import jwt  # PyJWT

from sqlalchemy.orm import Session
from database import get_db
from models import User, Invitation  # 👈 solo lo que usamos aquí
from schemas import (
    UserCreate,
    LoginRequest,
    TokenResponse,
    UserReturn,
    RegisterWithInviteRequest,
)
from secrets import token_urlsafe


# ======================================================
# CONFIG JWT
# ======================================================
SECRET_KEY = os.getenv("SECRET_KEY", "galenos-secret-key")  # cámbiala en PRODUCCIÓN
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24h

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto"
)



# ======================================================
# UTILIDADES
# ======================================================
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ======================================================
# REGISTRO NORMAL (no lo usamos desde web, pero queda disponible)
# ======================================================
def register_user(user_data: UserCreate, db: Session):
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="El correo ya está registrado.")

    hashed = hash_password(user_data.password)

    user = User(
        email=user_data.email,
        password_hash=hashed,
        name=user_data.name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return user


# ======================================================
# LOGIN
# ======================================================
def login_user(login_data: LoginRequest, db: Session):
    user = db.query(User).filter(User.email == login_data.email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Credenciales incorrectas.")

    if not verify_password(login_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Credenciales incorrectas.")

    user.last_login = datetime.utcnow()
    db.commit()

    access_token = create_access_token({"sub": str(user.id)})

    return TokenResponse(access_token=access_token)


# ======================================================
# OBTENER USUARIO ACTUAL (JWT)
# ======================================================
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            raise Exception("Token sin usuario")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")

    return user


# ======================================================
# CREAR INVITACIÓN ENTRE MÉDICOS
# ======================================================
def create_invitation(db: Session, current_user: User):
    token = token_urlsafe(32)

    invitation = Invitation(
        token=token,
        created_by_id=current_user.id,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=30),
        max_uses=1,
        used_count=0,
    )

    db.add(invitation)
    db.commit()
    db.refresh(invitation)

    return {"invite_url": f"https://galenos.pro/registro?token={token}"}


# ======================================================
# REGISTRAR USUARIO DESDE INVITACIÓN
# ======================================================
def register_user_with_invitation(data: RegisterWithInviteRequest, db: Session):
    # Buscar invitación
    invitation = db.query(Invitation).filter(Invitation.token == data.token).first()
    if not invitation:
        raise HTTPException(status_code=400, detail="Invitación no válida.")

    # Comprobar caducidad
    if invitation.expires_at and invitation.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="La invitación ha caducado.")

    # Comprobar usos
    if invitation.used_count >= invitation.max_uses:
        raise HTTPException(status_code=400, detail="La invitación ya ha sido utilizada.")

    # ¿Existe ya el correo?
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="El correo ya está registrado.")

    hashed = hash_password(data.password)

    user = User(
        email=data.email,
        password_hash=hashed,
        name=data.name,
    )
    db.add(user)

    # Actualizar invitación (sumar uso)
    invitation.used_count += 1

    db.commit()
    db.refresh(user)

    # Generar token como en login
    access_token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=access_token)


# ======================================================
# REGISTER MASTER (solo 1 vez y luego bloqueo)
# ======================================================
MASTER_LOCK_FILE = "master_lock.txt"

def register_master(db: Session, secret: str):
    # Verificar secreto
    if secret != "galenos123":
        raise HTTPException(status_code=403, detail="Secreto incorrecto.")

    # Si existe el lock, bloquear
    if os.path.exists(MASTER_LOCK_FILE):
        raise HTTPException(
            status_code=403,
            detail="El usuario master ya existe y el endpoint está bloqueado.",
        )

    # Truncado seguro para bcrypt (por si acaso)
    raw_password = "galenos8354@"
    safe_password = raw_password.encode("utf-8")[:72].decode("utf-8", "ignore")

    # Crear usuario master si no existe
    existing = db.query(User).filter(User.email == "soluzziona@gmail.com").first()
    if not existing:
        user = User(
            email="soluzziona@gmail.com",
            password_hash=hash_password(safe_password),
            name="Master",
        )
        db.add(user)
        db.commit()

    # Crear lock en disco para bloquear futuras ejecuciones
    try:
        with open(MASTER_LOCK_FILE, "w", encoding="utf-8") as f:
            f.write("locked")
    except Exception:
        # Si por lo que sea no se puede escribir, no pasa nada grave:
        # el usuario master ya está creado igualmente.
        pass

    return {"ok": True, "message": "Usuario master creado correctamente."}
