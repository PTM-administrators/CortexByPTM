"""
Vista creata da sola dalla chat: "mostrami i debitori" non deve più passare
dal configuratore manuale di Viste.jsx (segnalato più volte come difficile
— condition_type, colonna_data, sintassi {{colonna}}) per ottenere qualcosa
di riusabile. Riusa la stessa esplorazione già costruita per trovare la
tabella (services.esplorazione) e le stesse euristiche di colonna di
Andamenti (services.analisi_automatica) per decidere la modalità più
adatta di base.

`mode`/`colonna_*` sono override OPZIONALI: quando un LLM vero ha già visto
le colonne reali della tabella (vedi AgentBrain._contesto_decisione) può
scegliere da solo la modalità più adatta — anche "cards", che l'euristica
di base non propone mai da sola perché troppo rischiosa da indovinare senza
ragionamento vero (serve capire cosa significano "titolo"/"sottotitolo",
non solo che una colonna è testuale). Ogni override viene comunque
validato contro lo schema REALE prima di fidarsene: un LLM può sbagliare un
nome di colonna, e non deve mai bastare la sua parola per usarla in una
query su dati veri. Un override non valido (mode sconosciuto, colonna
inesistente) fa semplicemente ripiegare sull'euristica automatica, non fa
fallire la creazione — StubLLMClient (che non può fornire nessun override,
non ragiona) continua quindi a funzionare esattamente come prima.

Idempotente: la stessa tabella non genera una Vista nuova ad ogni domanda,
la riusa — altrimenti "mostrami i debitori" chiesto tre volte
produrrebbe tre Viste identiche nella pagina Viste.
"""
import json
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models.integrations import Integration
from app.models.saved_view import SavedView
from app.services import analisi_automatica, db_engine
from app.services.esplorazione import trova_tabella_per_nome

_MODI_VALIDI = ("table", "cards", "calendar")

# Nomi di colonna che fanno da "titolo" plausibile per un evento a
# calendario o una scheda — non un tipo SQL da riconoscere (qualunque testo
# va bene), solo un indizio su QUALE colonna testuale scegliere quando ce
# n'è più di una nella stessa tabella.
_INDIZI_TITOLO = ("nome", "descrizione", "titolo", "ragione_sociale", "cognome", "oggetto")


def nome_leggibile(nome_tabella: str) -> str:
    """"fondi_progetto" -> "Fondi progetto": una tabella creata dalla chat
    prende un nome leggibile invece del nome tecnico grezzo, così è anche
    più facile da richiamare dopo con "mostrami [nome]" (vedi
    agent_brain._try_saved_view)."""
    parole = nome_tabella.replace("_", " ").strip()
    return parole[:1].upper() + parole[1:] if parole else nome_tabella


def _colonna_titolo_plausibile(colonne: list[dict], colonne_pk: set[str], esclusa: str | None) -> str | None:
    testuali = [
        c for c in colonne
        if c["name"] not in colonne_pk
        and c["name"] != esclusa
        and analisi_automatica.e_tipo_testuale(str(c["type"]))
    ]
    if not testuali:
        return None
    per_nome = [c for c in testuali if any(p in c["name"].lower() for p in _INDIZI_TITOLO)]
    return (per_nome[0] if per_nome else testuali[0])["name"]


def _decidi_modalita_euristica(colonne: list[dict], pk: set[str]) -> tuple[str, dict[str, str]]:
    """"calendar" se la tabella ha sia una data plausibile sia un titolo
    testuale plausibile (un evento ha bisogno di entrambi per avere senso
    su un calendario) — altrimenti "table", la modalità universale che
    funziona su qualunque tabella senza dover indovinare altro. Codice
    puro, nessun ragionamento: non propone mai "cards" da sola (vedi
    modulo)."""
    col_data = analisi_automatica.colonna_data_plausibile(colonne)
    col_titolo = _colonna_titolo_plausibile(colonne, pk, col_data)
    if col_data and col_titolo:
        return "calendar", {"data": col_data, "titolo": col_titolo}
    return "table", {}


def _modalita_da_override(
    nomi_reali: set[str],
    mode: str | None,
    colonna_data: str | None,
    colonna_titolo: str | None,
    colonna_sottotitolo: str | None,
    colonna_badge: str | None,
) -> tuple[str, dict[str, str]] | None:
    """None se l'override (proposto da un LLM vero) non è utilizzabile —
    mode sconosciuto, o mancano le colonne che quella modalità richiede, o
    una colonna indicata non esiste davvero in questa tabella."""
    if mode not in _MODI_VALIDI:
        return None
    if mode == "table":
        return "table", {}
    if mode == "calendar":
        if colonna_data in nomi_reali and colonna_titolo in nomi_reali:
            return "calendar", {"data": colonna_data, "titolo": colonna_titolo}
        return None
    if mode == "cards":
        if colonna_titolo in nomi_reali:
            mapping = {"titolo": colonna_titolo}
            if colonna_sottotitolo in nomi_reali:
                mapping["sottotitolo"] = colonna_sottotitolo
            if colonna_badge in nomi_reali:
                mapping["badge"] = colonna_badge
            return "cards", mapping
        return None
    return None


def crea_o_riusa_vista(
    db: Session,
    integration: Integration,
    connection_string: str,
    termine: str,
    *,
    mode: str | None = None,
    colonna_data: str | None = None,
    colonna_titolo: str | None = None,
    colonna_sottotitolo: str | None = None,
    colonna_badge: str | None = None,
) -> tuple[SavedView, bool, str] | None:
    """Trova la tabella pertinente al `termine` (stessa ricerca
    dell'esplorazione libera, non solo tra le tabelle "interessanti" per un
    andamento: qui va bene qualunque tabella, anche senza colonna
    numerica), poi crea o riusa la Vista corrispondente — con la modalità
    scelta da un LLM vero se fornita e valida, altrimenti dall'euristica.

    Ritorna (vista, creata_ora, nome_tabella) — None se nessuna tabella
    sembra pertinente."""
    nome_tabella = trova_tabella_per_nome(connection_string, termine)
    if not nome_tabella:
        return None
    engine = db_engine.get_engine(connection_string)

    esistente = (
        db.query(SavedView)
        .filter(
            SavedView.organization_id == integration.organization_id,
            SavedView.integration_id == integration.id,
            SavedView.table_name == nome_tabella,
        )
        .first()
    )
    if esistente is not None:
        return esistente, False, nome_tabella

    insp = inspect(engine)
    colonne = insp.get_columns(nome_tabella)
    pk = set((insp.get_pk_constraint(nome_tabella) or {}).get("constrained_columns") or [])
    nomi_reali = {c["name"] for c in colonne}

    override = _modalita_da_override(nomi_reali, mode, colonna_data, colonna_titolo, colonna_sottotitolo, colonna_badge)
    mode_finale, mapping_finale = override if override is not None else _decidi_modalita_euristica(colonne, pk)

    vista = SavedView(
        organization_id=integration.organization_id,
        integration_id=integration.id,
        table_name=nome_tabella,
        name=nome_leggibile(nome_tabella),
        mode=mode_finale,
        column_mapping=json.dumps(mapping_finale),
        row_actions="[]",
    )
    db.add(vista)
    db.commit()
    db.refresh(vista)
    return vista, True, nome_tabella
