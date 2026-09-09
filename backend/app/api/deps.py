"""
Dependency FastAPI condivise tra i router che operano su un'integrazione di tipo
database (Data Explorer generico, motore contabile): risolvono l'integrazione,
verificano che appartenga all'azienda (organization) dell'utente autenticato —
non al singolo utente, così ogni amministratore dell'azienda vi accede — e
decifrano le credenziali ritornando la connection string. `integration_id`
viene risolto automaticamente da FastAPI dal path del router che la usa (deve
contenere `{integration_id}`).
"""
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.security import decrypt_credentials
from app.database import get_db
from app.models.integrations import Integration
from app.models.membership import RUOLO_ADMIN, ruolo_attivo
from app.models.user import User
from app.services import data_source

# Riesportato qui per comodità di import (`from app.api.deps import get_role_attiva`
# era già in uso prima di spostare l'implementazione in models/membership.py
# per evitare un import circolare con api.auth, che la usa anche in /me).
get_role_attiva = ruolo_attivo


def require_admin(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    """Dependency per gli endpoint che modificano qualcosa di persistente o
    inviano qualcosa verso l'esterno (integrazioni, regole di segnalazione,
    team, conferma di email/azioni pendenti, scrittura sui dati collegati) —
    un utente "sola lettura" può vedere tutto ma non toccare nulla di
    questo. Introdotta il 3 settembre 2026 (vedi models/membership.py)."""
    if ruolo_attivo(db, current_user) != RUOLO_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Serve un ruolo di amministratore per questa azione.",
        )
    return current_user


def get_connection_string(
    integration_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> str:
    integration = db.get(Integration, integration_id)
    if integration is None or integration.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integrazione non trovata")

    credentials = decrypt_credentials(integration.credentials)
    connection_string = credentials.get("connection_string")
    if not connection_string:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Questa integrazione non ha un database esplorabile",
        )
    return connection_string


def get_data_source(
    integration_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> data_source.DataSource:
    """Come get_connection_string, ma per una sorgente esplorabile qualunque
    (database O API REST — vedi app.services.data_source): usata dagli
    endpoint di sola lettura del Data Explorer, che non devono sapere quale
    delle due stanno leggendo."""
    integration = db.get(Integration, integration_id)
    if integration is None or integration.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integrazione non trovata")
    try:
        return data_source.resolve(integration)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
