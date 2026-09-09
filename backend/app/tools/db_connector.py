"""
Connessione ai Database esterni dei clienti per leggere/scrivere dati (es. gestionali).
"""
from typing import Any

from sqlalchemy import create_engine, text


def run_query(connection_string: str, query: str, params: dict[str, Any] | None = None) -> list[dict]:
    """Esegue una query di sola lettura su un DB esterno del cliente e ritorna le righe."""
    engine = create_engine(connection_string)
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            return [dict(row._mapping) for row in result]
    finally:
        engine.dispose()
