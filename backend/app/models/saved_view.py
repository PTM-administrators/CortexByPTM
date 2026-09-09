"""
Viste salvate: come un'organizzazione vuole vedere una tabella di un database
collegato (Hub Integrazioni) — a schede, a calendario o a tabella con azioni
per riga — senza che serva scrivere codice per ogni nuovo settore.

Generalizza il "visualize_tool" della finanza no-profit (che conosce solo il
suo schema) a qualunque azienda: un immobiliare mappa le sue colonne per
vedere annunci a schede, un barbiere le sue per un calendario appuntamenti,
un'azienda qualunque aggiunge un bottone "Sollecito" su una tabella di
debitori. Non richiede un LLM: la mappatura la sceglie l'utente una volta,
poi la vista si ri-genera da sola.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SavedView(Base):
    __tablename__ = "saved_views"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id"), nullable=False)

    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)  # "table" | "cards" | "calendar"

    # JSON serializzato (vedi app.services.view_config): come le colonne della
    # tabella si mappano ai ruoli che la modalità richiede (es. per "cards":
    # {"titolo": "nome_annuncio", "sottotitolo": "prezzo"}).
    column_mapping: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # JSON serializzato: lista di azioni disponibili sulla riga (solo per
    # mode="table"), es. [{"nome": "Sollecito", "to_colonna": "email",
    # "oggetto_template": "...", "corpo_template": "Ciao {{nome}}, ..."}].
    row_actions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    organization = relationship("Organization")
    integration = relationship("Integration")
