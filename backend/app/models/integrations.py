"""
Tabella dell'Hub Integrazioni: le credenziali esterne dell'azienda (Gmail,
Stripe, database ERP, ecc.) usate dall'Agente AI per eseguire azioni reali.

Appartengono all'organizzazione (azienda), non al singolo utente che le ha
create: così tutti gli amministratori dell'azienda le vedono e le usano.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Integration(Base):
    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)

    # Nome scelto dall'utente (es. "Database Sampeyre", "API Portale annunci"):
    # senza, integrazioni dello stesso provider sono indistinguibili tra loro
    # ("custom_db #3" non dice nulla). Nullable solo per le righe create prima
    # di questo campo — api/integrations.py._to_response ripiega su un nome
    # leggibile per quelle, ma ogni nuova integrazione ne richiede uno.
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # es. "gmail", "stripe", "sql_erp", "custom_db", "cortex_managed_db"
    provider: Mapped[str] = mapped_column(String(100), nullable=False)

    # Credenziali cifrate (vedi app.core.security.encrypt_credentials/decrypt_credentials).
    # Contengono un JSON serializzato, mai salvato in chiaro: la forma dei campi
    # dipende dal provider (es. {"api_key": ...} oppure {"connection_string": ...}).
    credentials: Mapped[str] = mapped_column(Text, nullable=False)

    # "connected" (default), "error", "disconnected"
    status: Mapped[str] = mapped_column(String(50), default="connected", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    organization = relationship("Organization", back_populates="integrations")
