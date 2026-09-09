"""
Template per il provisioning di un database gestito da Cortex (provider
"cortex_managed_db"): ogni template è uno schema + eventuali dati di partenza,
pensato per essere riusabile da qualunque tenant con esigenze simili, non da
uno solo. Il primo template ("nonprofit_accounting") nasce dalle categorie del
piano di progetto della Casa Diocesana di Sampeyre, ma qualunque altra
associazione/diocesi con la stessa esigenza contabile può partire da qui.

Ogni database creato da un template è un file SQLite indipendente, separato dal
database interno di Cortex (vedi PLAN.md, decisione dell'11 agosto 2026): i dati
di un tenant non vivono nello stesso database di un altro.
"""
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    create_engine,
    func,
    inspect,
    text,
)

# Codice, nome, gruppo (come nel piano di progetto), tipo (entrata|uscita|cespite|patrimoniale).
NONPROFIT_CATEGORIE_SEED: list[tuple[str, str, str, str]] = [
    # Entrate — Attività commerciale (soggiorni e servizi)
    ("A1.1", "Campi AC invernali", "Entrate — Attività commerciale", "entrata"),
    ("A1.2", "Campi AC estivi", "Entrate — Attività commerciale", "entrata"),
    ("A1.3", "Parrocchie e AC di altre Diocesi", "Entrate — Attività commerciale", "entrata"),
    ("A1.4", "Parrocchie e AC Diocesi di Asti", "Entrate — Attività commerciale", "entrata"),
    ("A1.5", "Ricavi da privati", "Entrate — Attività commerciale", "entrata"),
    ("A1.6", "Campo Famiglie AC e Campo Biblico", "Entrate — Attività commerciale", "entrata"),
    ("A1.7", "Altri soggiorni", "Entrate — Attività commerciale", "entrata"),
    ("A1.8", "Enti e gruppi non religiosi", "Entrate — Attività commerciale", "entrata"),
    # Entrate — Attività istituzionale
    ("A2.1", "Interessi bancari e da vendita titoli", "Entrate — Attività istituzionale", "entrata"),
    ("A2.2", "Contributi liberali da Enti pubblici e privati", "Entrate — Attività istituzionale", "entrata"),
    ("A2.3", "Contributi liberali da Parrocchie e benefattori", "Entrate — Attività istituzionale", "entrata"),
    ("A2.4", "Contributi liberali (donazioni e offerte da privati)", "Entrate — Attività istituzionale", "entrata"),
    ("A2.5", "Cessione energia da fotovoltaico", "Entrate — Attività istituzionale", "entrata"),
    ("A2.6", "Plusvalenze", "Entrate — Attività istituzionale", "entrata"),
    ("B1.1", "Fondo di solidarietà", "Entrate — Attività istituzionale", "entrata"),
    # Uscite — Materie prime e beni di consumo
    ("D1.1", "Materie prime", "Uscite — Materie prime e beni di consumo", "uscita"),
    ("D1.2", "Materie sussidiarie, imballaggi, ecc.", "Uscite — Materie prime e beni di consumo", "uscita"),
    ("D1.3", "Materie di consumo", "Uscite — Materie prime e beni di consumo", "uscita"),
    ("D1.4", "Materiale di cancelleria", "Uscite — Materie prime e beni di consumo", "uscita"),
    ("D1.5", "Materiale di pulizia", "Uscite — Materie prime e beni di consumo", "uscita"),
    ("D1.6", "Indumenti di lavoro", "Uscite — Materie prime e beni di consumo", "uscita"),
    ("D1.7", "Medicinali e materiale vario infermeria", "Uscite — Materie prime e beni di consumo", "uscita"),
    ("D1.8", "Pezzi di ricambio su beni propri", "Uscite — Materie prime e beni di consumo", "uscita"),
    ("D1.9", "Acquisto beni di importo inferiore a 516 €", "Uscite — Materie prime e beni di consumo", "uscita"),
    ("D1.10", "Gasolio per riscaldamento", "Uscite — Materie prime e beni di consumo", "uscita"),
    # Uscite — Utenze e servizi industriali
    ("D2.1", "Energia elettrica", "Uscite — Utenze e servizi industriali", "uscita"),
    ("D2.2", "Spese di riscaldamento", "Uscite — Utenze e servizi industriali", "uscita"),
    ("D2.3", "Acqua potabile e gas", "Uscite — Utenze e servizi industriali", "uscita"),
    ("D2.4", "Canoni di assistenza", "Uscite — Utenze e servizi industriali", "uscita"),
    # Uscite — Servizi commerciali e generali
    ("D2.5", "Spese di pubblicità e propaganda", "Uscite — Servizi commerciali e generali", "uscita"),
    ("D2.6", "Premi assicurativi", "Uscite — Servizi commerciali e generali", "uscita"),
    ("D2.7", "Spese postali", "Uscite — Servizi commerciali e generali", "uscita"),
    ("D2.8", "Spese telefoniche", "Uscite — Servizi commerciali e generali", "uscita"),
    ("D2.9", "Servizi amministrativi e contabili", "Uscite — Servizi commerciali e generali", "uscita"),
    ("D2.10", "Servizi e prestazioni di professionisti", "Uscite — Servizi commerciali e generali", "uscita"),
    ("D2.11", "Ricerca del personale", "Uscite — Servizi commerciali e generali", "uscita"),
    ("D2.12", "Visite ed esami medici per dipendenti", "Uscite — Servizi commerciali e generali", "uscita"),
    ("D2.13", "Aggiornamento e formazione personale", "Uscite — Servizi commerciali e generali", "uscita"),
    ("D2.14", "Servizi vari generali e amministrativi", "Uscite — Servizi commerciali e generali", "uscita"),
    ("D2.15", "Manutenzione/riparazione attrezzature proprie", "Uscite — Servizi commerciali e generali", "uscita"),
    (
        "D2.16",
        "Manutenzione/riparazione impianti e macchinari propri",
        "Uscite — Servizi commerciali e generali",
        "uscita",
    ),
    ("D2.17", "Servizi e spese di pulizia", "Uscite — Servizi commerciali e generali", "uscita"),
    # Uscite — Godimento beni di terzi
    ("D3.1", "Noleggio mezzi e attrezzature", "Uscite — Godimento beni di terzi", "uscita"),
    # Uscite — Personale
    ("D4.1", "Salari e oneri sociali per operai", "Uscite — Personale", "uscita"),
    ("D4.3", "Contributi assicurativi obbligatori contro infortuni", "Uscite — Personale", "uscita"),
    # Uscite — Oneri diversi di gestione
    ("D5.1", "Tassa raccolta rifiuti", "Uscite — Oneri diversi di gestione", "uscita"),
    ("D5.2", "Interessi passivi di mora e diritti camerali", "Uscite — Oneri diversi di gestione", "uscita"),
    # Uscite — Ammortamenti
    (
        "D6.1",
        "Quote di ammortamento (calcolate automaticamente dal registro Cespiti)",
        "Uscite — Ammortamenti",
        "uscita",
    ),
    ("D6.2", "Spese non deducibili fiscalmente", "Uscite — Ammortamenti", "uscita"),
    # Uscite — Oneri bancari
    ("D7.1", "Commissioni e spese bancarie e postali", "Uscite — Oneri bancari", "uscita"),
    # Cespiti — beni pluriennali
    ("C1.1", "Manutenzioni/riparazioni pluriennali", "Cespiti — beni pluriennali", "cespite"),
    ("C1.2", "Fabbricati strumentali", "Cespiti — beni pluriennali", "cespite"),
    ("C1.3", "Macchinari", "Cespiti — beni pluriennali", "cespite"),
    ("C1.4", "Attrezzatura varia e minuta", "Cespiti — beni pluriennali", "cespite"),
    ("C1.5", "Arredamento", "Cespiti — beni pluriennali", "cespite"),
    ("C1.6", "Attrezzature concesse in locazione", "Cespiti — beni pluriennali", "cespite"),
    # Movimenti patrimoniali — non entrano nel Conto Economico
    ("B1.2", "Caparre per prenotazioni e acconti su fatture", "Movimenti patrimoniali", "patrimoniale"),
    ("E1.x", "Acquisto titoli e investimenti", "Movimenti patrimoniali", "patrimoniale"),
]


def _blank_metadata() -> MetaData:
    return MetaData()


def nonprofit_accounting_metadata() -> MetaData:
    """Schema del template 'nonprofit_accounting' (categorie/movimenti/cespiti/...).

    Pubblica (non prefissata da `_`) perché è il contratto di schema condiviso
    con `app.services.accounting_engine`, che sa interpretare questi nomi di
    tabella/colonna — non solo chi provisiona il database.
    """
    metadata = MetaData()
    Table(
        "categorie",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("codice", String(20), nullable=False, unique=True),
        Column("nome", String(255), nullable=False),
        Column("gruppo", String(255), nullable=False),
        Column("tipo", String(20), nullable=False),  # entrata | uscita | cespite | patrimoniale
    )
    Table(
        "movimenti",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("data", Date, nullable=False),
        Column("descrizione", String(500), nullable=False),
        Column("importo", Numeric(12, 2), nullable=False),
        Column("iva", Numeric(12, 2), nullable=True),
        Column("conto", String(20), nullable=False),  # Banca | Cassa | Titoli
        Column("categoria_codice", String(20), nullable=False),
        Column("fondo_progetto", String(255), nullable=True),
        Column("allegato_path", String(500), nullable=True),
        # server_default (non default=): deve valere anche quando la riga viene
        # inserita passando dalla reflection del Data Explorer generico, che non
        # conosce i default "lato Python" della metadata originale — solo quelli
        # scritti davvero nello schema del database.
        Column("creato_il", DateTime, nullable=False, server_default=func.now()),
        # Impostato dalla riconciliazione bancaria (app.services.bank_reconciliation)
        # quando il movimento viene abbinato a una riga dell'estratto conto.
        Column("riconciliato", Boolean, nullable=False, server_default="0"),
    )
    Table(
        "cespiti",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("descrizione", String(255), nullable=False),
        Column("categoria_codice", String(20), nullable=False),
        Column("data_acquisto", Date, nullable=False),
        Column("costo", Numeric(12, 2), nullable=False),
        Column("aliquota_ammortamento", Numeric(5, 2), nullable=False),
        Column("fondo_ammortamento", Numeric(12, 2), nullable=False, server_default="0"),
    )
    Table(
        "fondi_progetto",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("nome", String(255), nullable=False),
        Column("descrizione", String(500), nullable=True),
    )
    Table(
        "soglie_budget",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("categoria_codice", String(20), nullable=False),
        Column("soglia_mensile", Numeric(12, 2), nullable=False),
    )
    return metadata


def _seed_nothing(engine: Any, metadata: MetaData) -> None:
    return None


def _seed_nonprofit_accounting(engine: Any, metadata: MetaData) -> None:
    categorie = metadata.tables["categorie"]
    with engine.begin() as conn:
        conn.execute(
            categorie.insert(),
            [
                {"codice": codice, "nome": nome, "gruppo": gruppo, "tipo": tipo}
                for codice, nome, gruppo, tipo in NONPROFIT_CATEGORIE_SEED
            ],
        )


TEMPLATES: dict[str, dict[str, Any]] = {
    "blank": {
        "label": "Vuoto",
        "description": "Un database vuoto, senza tabelle: da collegare in un secondo momento a uno strumento esterno o da popolare manualmente.",
        "metadata_factory": _blank_metadata,
        "seed": _seed_nothing,
    },
    "nonprofit_accounting": {
        "label": "Contabilità no-profit",
        "description": (
            "Categorie, Movimenti (Prima Nota), Cespiti, Fondi/progetto e Soglie budget — "
            "schema e categorie ripresi dal piano di progetto della Casa Diocesana di Sampeyre, "
            "riusabile da qualunque associazione/diocesi con la stessa esigenza."
        ),
        "metadata_factory": nonprofit_accounting_metadata,
        "seed": _seed_nonprofit_accounting,
    },
}


def get_template_catalog() -> list[dict[str, str]]:
    return [{"template": key, "label": v["label"], "description": v["description"]} for key, v in TEMPLATES.items()]


def provision_database(db_path: Path, template: str) -> str:
    """Crea un nuovo file SQLite con lo schema (ed eventuale seed) del template scelto.
    Ritorna la connection string da salvare (cifrata) nell'Integration."""
    template_def = TEMPLATES.get(template, TEMPLATES["blank"])
    connection_string = f"sqlite:///{db_path}"
    engine = create_engine(connection_string)
    try:
        metadata_factory: Callable[[], MetaData] = template_def["metadata_factory"]
        metadata = metadata_factory()
        metadata.create_all(engine)
        template_def["seed"](engine, metadata)
    finally:
        engine.dispose()
    return connection_string


def add_riconciliato_column_if_missing(connection_string: str) -> bool:
    """Aggiunge la colonna 'riconciliato' a movimenti se manca — serve per i
    database provisionati prima che questa colonna esistesse nel template
    (es. il db Sampeyre creato in Fase B). Non è un sistema di migrazione
    generico (nessun versionamento): una toppa mirata per questo campo,
    finché non serve qualcosa di più strutturato. Ritorna True se applicata."""
    engine = create_engine(connection_string)
    try:
        inspector = inspect(engine)
        if "movimenti" not in inspector.get_table_names():
            return False
        colonne = {c["name"] for c in inspector.get_columns("movimenti")}
        if "riconciliato" in colonne:
            return False
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE movimenti ADD COLUMN riconciliato BOOLEAN NOT NULL DEFAULT 0"))
        return True
    finally:
        engine.dispose()
