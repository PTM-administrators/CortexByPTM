"""
Connessione al Database tramite SQLAlchemy (PostgreSQL in produzione, SQLite in locale).
"""
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

# backend/ (due livelli sopra questo file: app/database.py -> app/ -> backend/)
_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _resolve_database_url(raw_url: str) -> str:
    """Se DATABASE_URL è uno SQLite con percorso relativo, lo ancora a backend/
    invece di lasciarlo dipendere dalla cartella da cui viene lanciato il processo
    (uvicorn, alembic, uno script...): altrimenti si finisce con più file .db
    diversi a seconda di da dove si avvia il comando."""
    prefix = "sqlite:///"
    if not raw_url.startswith(prefix) or raw_url.startswith("sqlite:////"):
        return raw_url  # non SQLite, oppure già un percorso assoluto (////)

    relative_path = raw_url[len(prefix):]
    absolute_path = (_BACKEND_DIR / relative_path).resolve()
    return f"{prefix}{absolute_path}"


DATABASE_URL = _resolve_database_url(settings.DATABASE_URL)

# Dove vivono i database "gestiti" (provider cortex_managed_db): un file SQLite
# per tenant, separato dal database interno di Cortex sopra e dagli altri
# tenant. Stessa logica di ancoraggio a backend/ per non dipendere dalla cwd.
TENANT_DATA_DIR = _BACKEND_DIR / "tenant_data"

# SQLite richiede questo argomento extra per funzionare con più thread (es. FastAPI + Uvicorn).
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Classe base per tutti i modelli ORM."""


def get_db() -> Generator:
    """Dependency FastAPI: fornisce una sessione DB e la chiude a fine richiesta."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
