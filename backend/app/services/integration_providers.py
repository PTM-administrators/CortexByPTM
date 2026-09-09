"""
Catalogo dei provider supportati dall'Hub Integrazioni. Per ognuno definisce:
- `kind`: come il resto del sistema deve trattarlo
    - "api": credenziali per chiamare un servizio esterno (Gmail, Stripe, ...),
      usate dai tool dell'agente (email_tool, ecc.), non esplorabile come dati.
    - "database_external": l'azienda ha già un proprio database/ERP e fornisce
      lei la stringa di connessione. Esplorabile dal Data Explorer generico.
    - "database_managed": non ha un proprio database, Cortex ne provisiona uno
      dedicato e isolato (vedi app.services.db_templates). Stesso Data Explorer
      generico, la sola differenza è chi ospita i dati.
    - "data_api": l'azienda non ha un database ma un'API REST da cui leggere i
      dati (es. un portale di annunci) — esplorabile con la stessa logica dei
      database ma tramite app.services.api_connector invece di SQL; vedi
      app.services.data_source per il punto in cui le due strade si uniscono.
- `fields`: quali campi mostrare nel form (vuoto per i provider "managed": lì si
  sceglie un template, non si inseriscono credenziali).

Il frontend costruisce il form di Integrations.jsx e il Data Explorer da questo
catalogo, invece di avere i provider hardcodati nel componente React.
"""
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.integrations import Integration

PROVIDER_CATALOG: dict[str, dict[str, Any]] = {
    # "label"/"description": in italiano semplice, per chi apre questo form
    # senza sapere cosa significhi "sql_erp" o "custom_db" — mostrati al
    # posto del nome tecnico del provider (vedi Integrations.jsx). L'ordine
    # qui sotto è anche l'ordine mostrato nel menu: il caso più comune di
    # chi collega la propria contabilità (gestionale esistente, o nessuno)
    # viene prima dei servizi accessori (email, pagamenti, IA).
    "cortex_managed_db": {
        "kind": "database_managed",
        "label": "Database creato da Cortex — consigliato se non hai nulla",
        "description": "Non hai ancora un gestionale? Cortex ne crea uno pronto all'uso in un click, senza credenziali da inserire.",
        "fields": [],
    },
    "sql_erp": {
        "kind": "database_external",
        "label": "Gestionale che usi già (es. Arca, altro ERP)",
        "description": "Ti colleghi al database del tuo gestionale già in uso — Cortex riconosce da solo di che tipo è.",
        "fields": [
            {
                "key": "connection_string",
                "label": "Stringa di connessione (es. postgresql://utente:password@host/db)",
                "default": "",
                "secret": True,
            },
        ],
    },
    "custom_db": {
        "kind": "database_external",
        "label": "Un altro database che hai già",
        "description": "Un database esistente non legato a un gestionale specifico.",
        "fields": [
            {"key": "connection_string", "label": "Stringa di connessione", "default": "", "secret": True},
        ],
    },
    "rest_api": {
        "kind": "data_api",
        "label": "Un'API invece di un database",
        "description": "I tuoi dati arrivano da un servizio web (es. un portale annunci) invece che da un database.",
        "fields": [
            {"key": "base_url", "label": "URL base (es. https://api.esempio.it)", "default": "", "secret": False},
            {
                "key": "list_path",
                "label": "Percorso elenco (es. /v1/annunci)",
                "default": "",
                "secret": False,
            },
            {
                "key": "list_items_path",
                "label": "Percorso dell'elenco nella risposta (vuoto se la risposta è già l'elenco, es. results)",
                "default": "",
                "secret": False,
                "required": False,
            },
            {"key": "id_field", "label": "Campo identificativo (es. id)", "default": "id", "secret": False},
            {
                "key": "detail_path_template",
                "label": "Percorso dettaglio, opzionale (es. /v1/annunci/{id})",
                "default": "",
                "secret": False,
                "required": False,
            },
            {
                "key": "auth_header",
                "label": "Header di autenticazione, opzionale (es. Authorization)",
                "default": "",
                "secret": False,
                "required": False,
            },
            {
                "key": "auth_value",
                "label": "Valore dell'header, opzionale",
                "default": "",
                "secret": True,
                "required": False,
            },
        ],
    },
    "gmail": {
        "kind": "api",
        "label": "Email (Gmail o altro SMTP)",
        "description": "Per mandare email da Cortex — solleciti, notifiche automatiche, riepiloghi.",
        "fields": [
            {"key": "smtp_host", "label": "Host SMTP", "default": "smtp.gmail.com", "secret": False},
            {"key": "smtp_port", "label": "Porta SMTP", "default": "587", "secret": False},
            {"key": "username", "label": "Indirizzo email", "default": "", "secret": False},
            {"key": "password", "label": "Password / App Password", "default": "", "secret": True},
        ],
    },
    "stripe": {
        "kind": "api",
        "label": "Stripe",
        "description": "Pagamenti e abbonamenti gestiti su Stripe.",
        "fields": [{"key": "api_key", "label": "Secret Key", "default": "", "secret": True}],
    },
    "openai": {
        "kind": "api",
        "label": "OpenAI (assistente IA reale, a pagamento)",
        "description": "Solo se vuoi che la chat capisca richieste libere invece del riconoscimento a pattern gratuito — genera costi reali.",
        "fields": [{"key": "api_key", "label": "API Key", "default": "", "secret": True}],
    },
}

# Fallback generico per provider non catalogati: un solo campo "api_key".
DEFAULT_PROVIDER: dict[str, Any] = {
    "kind": "api",
    "fields": [{"key": "api_key", "label": "Chiave API / Credenziale", "default": "", "secret": True}],
}


def get_provider_catalog() -> list[dict[str, Any]]:
    """Elenco dei provider noti (kind + campi), per popolare il form frontend."""
    return [{"provider": name, **entry} for name, entry in PROVIDER_CATALOG.items()]


def get_provider_kind(provider: str) -> str:
    return PROVIDER_CATALOG.get(provider, DEFAULT_PROVIDER)["kind"]


def is_database_provider(provider: str) -> bool:
    return get_provider_kind(provider) in ("database_external", "database_managed")


def find_first_database_integration(db: "Session", organization_id: int) -> "Integration | None":
    """Prima integrazione database dell'azienda (la più vecchia) — "il
    database collegato" quando nessuno lo specifica esplicitamente: usata
    dalla chat (agent_brain._handle_visualize), dalle notifiche automatiche
    (services/notifiche.py) e dal riepilogo della Dashboard. Centralizzata
    qui invece di essere reimplementata in ognuno di questi posti — prima
    di questa funzione lo era già in due."""
    from app.models.integrations import Integration  # import locale: evita un ciclo con i modelli

    integrazioni = (
        db.query(Integration)
        .filter(Integration.organization_id == organization_id)
        .order_by(Integration.created_at)
        .all()
    )
    for i in integrazioni:
        if is_database_provider(i.provider):
            return i
    return None
