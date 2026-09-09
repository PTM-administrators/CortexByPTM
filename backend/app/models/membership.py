"""
Appartenenza di un utente a un'azienda (organization) — un utente può avere
accesso a PIÙ aziende (es. chi segue Trevalli e anche la Casa Diocesana di
Sampeyre come clienti diversi), non solo a quella con cui si è registrato.

`User.organization_id` resta: rappresenta l'azienda "attiva" in questo
momento (quella su cui agiscono tutte le pagine/API esistenti, che
continuano a leggerlo senza modifiche — vedi api/auth.py.switch_organization)
— non più "l'unica azienda dell'utente", ma "quale delle sue aziende sta
guardando adesso". Questa tabella è invece l'elenco completo di quali
aziende un utente PUÒ guardare: un utente ha sempre almeno una Membership
(quella creata alla registrazione), e può accumularne altre unendosi con
il codice invito di un'altra azienda (vedi api/auth.py.join_organization)
o creandone di nuove come cliente aggiuntivo (api/auth.py.create_organization).
"""
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User

# "admin": può configurare integrazioni, segnalazioni, team, confermare
# l'invio di email/azioni pendenti — tutto quello che oggi fa qualunque
# utente. "readonly": può consultare dashboard/andamenti/contabilità/chat
# ma non modificare nulla di persistente né inviare nulla verso l'esterno
# (vedi api/deps.require_admin, applicato agli endpoint che mutano stato).
# Introdotto il 3 settembre 2026: prima chiunque avesse una Membership aveva
# accesso identico e totale, senza modo di dare a un dipendente del cliente
# un accesso di sola consultazione.
RUOLO_ADMIN = "admin"
RUOLO_READONLY = "readonly"


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="uq_membership_user_org"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default=RUOLO_ADMIN, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user = relationship("User")
    organization = relationship("Organization")


def ruolo_attivo(db: Session, user: "User") -> str:
    """Il ruolo di `user` nell'azienda ATTIVA in questo momento
    (user.organization_id) — non un ruolo globale: la stessa persona può
    essere admin della propria azienda e sola lettura in un'azienda cliente
    a cui è stata invitata, o viceversa. Funzione libera (non una dependency
    FastAPI) così sia api.deps (per require_admin) sia api.auth (per
    esporre il ruolo nella risposta di /me) possono usarla senza creare un
    'import circolare fra i due moduli. Se manca la Membership (non
    dovrebbe succedere: ogni azienda attiva ne richiede una) tratta come
    sola lettura per prudenza, non come admin."""
    membership = (
        db.query(Membership)
        .filter(Membership.user_id == user.id, Membership.organization_id == user.organization_id)
        .first()
    )
    return membership.role if membership else RUOLO_READONLY
