"""
Segnalazioni proattive: una regola che l'agente valuta da solo su una tabella
o risorsa collegata, senza che l'utente debba chiedere — es. "questo debitore
è scaduto da 30 giorni", "questa spesa è anomala". Generalizza lo stesso
principio delle Viste salvate (SavedView) a un caso diverso: non "come
mostrare i dati" ma "quando avvisare su questi dati".
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id"), nullable=False)

    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # "scadenza_superata" | "soglia_numerica" | "valore_anomalo"
    # (vedi app.services.alert_engine per il significato di ciascuna)
    condition_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # JSON serializzato: parametri della condizione, diversi per tipo — es.
    # {"colonna_data": "scadenza", "giorni_tolleranza": 0} per "scadenza_superata".
    config: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # Testo della segnalazione con {{colonna}} sostituibili (vedi
    # app.services.templating) — se vuoto si usa una descrizione generica.
    messaggio_template: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # JSON serializzato opzionale: {"to_colonna", "oggetto_template",
    # "corpo_template"} — se presente (to_colonna non vuoto), ogni
    # segnalazione NUOVA di questa regola prepara anche una bozza d'azione
    # pronta (vedi models.AzionePendente e services/notifiche.py), non solo
    # una notifica interna: es. il sollecito già scritto per il debitore
    # scaduto, pronto da confermare con un click invece di scriverlo da
    # zero. "{}" = nessuna azione collegata, solo la notifica come prima.
    azione_template: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    attiva: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    organization = relationship("Organization")
    integration = relationship("Integration")
