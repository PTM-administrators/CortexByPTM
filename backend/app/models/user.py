"""
Tabella Utenti: un login individuale. L'azienda a cui appartiene (nome,
settore, integrazioni) vive in models/organization.py — più utenti possono
condividere la stessa organization_id, cioè più amministratori con lo stesso
accesso ai dati dell'azienda.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    organization = relationship("Organization", back_populates="users")

    # Proxy verso l'organizzazione: tutto il codice scritto quando company_name
    # e industry erano colonne dirette di User (dashboard, agent_brain, schemi
    # Pydantic con from_attributes=True) continua a funzionare senza modifiche.
    @property
    def company_name(self) -> str:
        return self.organization.company_name

    @property
    def industry(self) -> str:
        return self.organization.industry
