"""
Un'azione pronta preparata da Cortex da solo (tipicamente un sollecito a un
debitore/fornitore scaduto) — non inviata subito: resta in attesa che un
amministratore la confermi con un click, stesso principio di sicurezza già
usato per le email preparate dall'agente in chat (app.services.agent_state.
PendingAction), ma con due differenze concrete che qui contano:

- persistita su tabella, non tenuta in memoria di processo: preparata dal
  ciclo automatico in background (services/notifiche.py), deve restare
  visibile anche ore dopo, anche dopo un riavvio del server — non solo
  finché dura la sessione di chi era loggato in quel momento (che spesso
  non è nessuno: il ciclo gira da solo ogni 30 minuti).
- legata all'azienda (organization_id), non a un singolo utente: qualunque
  amministratore di quell'azienda deve poterla vedere e confermare, non
  solo chi ha aperto la chat che l'ha generata (qui nessuno l'ha generata,
  l'ha fatto Cortex da solo).
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AzionePendente(Base):
    __tablename__ = "azioni_pendenti"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)

    # Cosa ha fatto scattare questa bozza, leggibile da un umano — es.
    # "Debitori scaduti — Mario Rossi" (nome regola + un riferimento alla riga).
    origine: Mapped[str] = mapped_column(String(255), nullable=False)

    to_address: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # "in_attesa" | "inviata" | "rifiutata"
    stato: Mapped[str] = mapped_column(String(20), nullable=False, default="in_attesa")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    organization = relationship("Organization")
