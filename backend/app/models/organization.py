"""
Tabella Organizzazioni (aziende/tenant): rappresenta l'azienda, separata dal
singolo login (vedi models/user.py). Le integrazioni e i dati collegati
appartengono all'organizzazione, non a un utente — così più amministratori
con account distinti vedono e gestiscono gli stessi dati (decisione confermata
nel piano di progetto: "nessun limite al numero di amministratori").
"""
import secrets
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def genera_invite_code() -> str:
    return secrets.token_urlsafe(9)  # ~12 caratteri, url-safe, sufficiente per un codice invito


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Settore aziendale: determina come si adatta la UI (vedi services/industry_rules.py)
    industry: Mapped[str] = mapped_column(String(100), default="generic")

    # Codice che un nuovo amministratore usa in fase di registrazione per unirsi
    # a questa organizzazione invece di crearne una nuova (vedi api/auth.py).
    # Rigenerabile da un amministratore esistente (api/team.py) se compromesso.
    invite_code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, nullable=False, default=genera_invite_code
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    users = relationship("User", back_populates="organization")
    integrations = relationship(
        "Integration", back_populates="organization", cascade="all, delete-orphan"
    )
