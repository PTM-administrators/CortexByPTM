"""
Hashing delle password, gestione dei JWT Token e cifratura delle credenziali
delle integrazioni (Hub Integrazioni) salvate a riposo nel database.
"""
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    """Genera l'hash sicuro di una password in chiaro."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica che una password in chiaro corrisponda all'hash memorizzato."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))



def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Crea un JWT firmato contenente i dati passati (es. {"sub": user_id})."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decodifica e verifica un JWT. Ritorna None se non valido o scaduto."""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None


@lru_cache
def _fernet() -> Fernet:
    """Chiave di cifratura simmetrica per le credenziali delle integrazioni.

    Derivata da SECRET_KEY (sha256 -> base64 urlsafe) invece di richiedere una
    variabile d'ambiente dedicata: niente nuovo segreto da configurare/perdere,
    a costo di legare la cifratura alla rotazione di SECRET_KEY (se cambia,
    le credenziali già salvate non sono più decifrabili).
    """
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_credentials(data: dict[str, Any]) -> str:
    """Cifra un dizionario di credenziali (es. api key, connection string) in una stringa."""
    raw = json.dumps(data).encode("utf-8")
    return _fernet().encrypt(raw).decode("utf-8")


def decrypt_credentials(token: str) -> dict[str, Any]:
    """Decifra le credenziali salvate. Ritorna {} se il token non è valido/leggibile."""
    try:
        raw = _fernet().decrypt(token.encode("utf-8"))
        return json.loads(raw)
    except (InvalidToken, ValueError, json.JSONDecodeError):
        return {}


def mask_credentials(data: dict[str, Any]) -> dict[str, str]:
    """Ritorna una versione mascherata delle credenziali, sicura da esporre al frontend.

    Mostra solo la lunghezza e le ultime 4 cifre/lettere del valore, mai il valore intero.
    """
    masked: dict[str, str] = {}
    for key, value in data.items():
        text = str(value)
        if len(text) <= 4:
            masked[key] = "•" * len(text)
        else:
            masked[key] = "•" * (len(text) - 4) + text[-4:]
    return masked
