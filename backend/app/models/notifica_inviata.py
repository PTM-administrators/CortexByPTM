"""
Registro delle notifiche automatiche già inviate (vedi app.services.notifiche
e app.services.scheduler) — evita di rimandare la stessa email ad ogni ciclo:
una segnalazione che resta vera nel tempo (es. una scadenza non ancora
saldata) genera un'email solo alla prima comparsa, non una ogni 30 minuti;
il riepilogo mattutino ne genera al massimo una al giorno per azienda.

`chiave` identifica univocamente COSA è stato notificato (non CHI l'ha
ricevuto): "segnalazione:{regola_id}:{pk}" per una singola riga che ha fatto
scattare una regola, "riepilogo:{data}" per il riepilogo mattutino del
giorno. Un vincolo di unicità su (organization_id, chiave) rende il controllo
"è già stata notificata?" un'unica query indicizzata, e impedisce doppi invii
anche se il ciclo dovesse sovrapporsi a se stesso.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class NotificaInviata(Base):
    __tablename__ = "notifiche_inviate"
    __table_args__ = (UniqueConstraint("organization_id", "chiave", name="uq_notifica_org_chiave"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    chiave: Mapped[str] = mapped_column(String(255), nullable=False)

    inviata_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    organization = relationship("Organization")
