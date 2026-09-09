"""
Segnalazione creata da sola dalla chat — "avvisami quando un debitore è in
ritardo" o "crea una segnalazione per le spese maggiori di 1000 euro" non
devono più passare dal configuratore manuale di Segnalazioni.jsx.

`crea_o_riusa_segnalazione` è la funzione generica, guidata da un LLM vero
che ha già visto le colonne REALI della tabella candidata (vedi
AgentBrain._contesto_decisione, che le inietta nel contesto prima ancora di
decidere) e sceglie da solo condition_type/colonna/soglia tra tutti e tre i
tipi supportati da alert_engine — non più solo i due che un'espressione
regolare riusciva a riconoscere. Feedback esplicito dell'utente (3 settembre
2026): "non deve usare template predefiniti ma la chat deve capire
qualsiasi cosa voglia l'utente e farlo" — aggiungere un "tipo 3" a mano,
come fatto la volta precedente per "soglia numerica", era la risposta
sbagliata alla domanda giusta: il problema non erano i tipi mancanti, era
che a decidere fosse sempre e solo codice scritto in anticipo, mai un
ragionamento vero sulla frase e sullo schema reale.

Le due funzioni "_scadenza"/"_soglia" restano come ripiego per
StubLLMClient (che non ragiona, riconosce solo espressioni regolari — un
limite onesto e non aggirabile del livello gratuito, non di questo modulo):
sono ora thin wrapper della funzione generica, non più codice duplicato.
"valore_anomalo" resta fuori da quel ripiego a pattern (troppo ambiguo da
un'espressione regolare) ma è pienamente disponibile quando è un LLM vero a
scegliere.
"""
import json
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models.alert_rule import AlertRule
from app.models.integrations import Integration
from app.services import alert_engine, analisi_automatica, data_source, db_engine
from app.services.esplorazione import trova_tabella_per_nome
from app.services.vista_automatica import nome_leggibile

_TIPI_VALIDI = ("scadenza_superata", "soglia_numerica", "valore_anomalo")


def _colonne_e_pk(connection_string: str, nome_tabella: str) -> tuple[list[dict], set[str]]:
    engine = db_engine.get_engine(connection_string)
    insp = inspect(engine)
    colonne = insp.get_columns(nome_tabella)
    pk = set((insp.get_pk_constraint(nome_tabella) or {}).get("constrained_columns") or [])
    return colonne, pk


def _trova_o_crea(
    db: Session,
    integration: Integration,
    nome_tabella: str,
    condition_type: str,
    name: str,
    config: dict[str, Any],
) -> tuple[AlertRule, bool]:
    """Riusa una regola esistente SOLO se ha la stessa configurazione
    esatta, non solo la stessa tabella+tipo — altrimenti "spese maggiori di
    1000" chiesto dopo un "maggiori di 500" già creato riuserebbe
    silenziosamente la soglia vecchia invece di applicare quella appena
    richiesta. Una configurazione diversa sulla stessa tabella diventa una
    regola nuova e distinta, non un aggiornamento di quella vecchia (che
    resta attiva finché non viene eliminata a mano)."""
    config_serializzata = json.dumps(config)
    esistente = (
        db.query(AlertRule)
        .filter(
            AlertRule.organization_id == integration.organization_id,
            AlertRule.integration_id == integration.id,
            AlertRule.table_name == nome_tabella,
            AlertRule.condition_type == condition_type,
            AlertRule.config == config_serializzata,
        )
        .first()
    )
    if esistente is not None:
        return esistente, False

    regola = AlertRule(
        organization_id=integration.organization_id,
        integration_id=integration.id,
        table_name=nome_tabella,
        name=name,
        condition_type=condition_type,
        config=config_serializzata,
    )
    db.add(regola)
    db.commit()
    db.refresh(regola)
    return regola, True


def _valuta_ora(integration: Integration, nome_tabella: str, condition_type: str, config: dict) -> list[dict[str, Any]]:
    source = data_source.resolve(integration)
    risultato = data_source.list_rows(source, nome_tabella, limit=alert_engine.LIMITE_RIGHE, offset=0)
    return alert_engine.valuta_condizione(condition_type, risultato["rows"], config)


def _nome_regola(nome_tabella: str, condition_type: str, config: dict[str, Any]) -> str:
    base = nome_leggibile(nome_tabella)
    if condition_type == "scadenza_superata":
        return f"{base} scaduti"
    if condition_type == "soglia_numerica":
        simbolo = {">": "sopra", "<": "sotto"}.get(config["operatore"], config["operatore"])
        return f"{base} {simbolo} {config['soglia']:g}"
    return f"{base} anomali ({config['colonna']})"


def crea_o_riusa_segnalazione(
    db: Session,
    integration: Integration,
    connection_string: str,
    termine: str,
    condition_type: str,
    *,
    colonna: str | None = None,
    colonna_data: str | None = None,
    operatore: str | None = None,
    soglia: float | None = None,
    giorni_tolleranza: int = 0,
    colonna_gruppo: str | None = None,
    soglia_deviazioni: float = 2.0,
) -> tuple[AlertRule, bool, list[dict[str, Any]]] | None:
    """Versione generica: trova la tabella pertinente, poi valida la/e
    colonna/e indicate contro lo schema REALE — mai fidata ciecamente su un
    nome scelto da un LLM, che può sbagliare, prima di usarla in una query
    su dati veri. Se la colonna indicata non esiste in questa tabella,
    ripiega sull'euristica automatica (stessa di Andamenti) invece di
    fallire subito: un tentativo in più prima di arrendersi. None se il
    tipo non è valido, la tabella non si trova, o nessuna colonna adatta
    esiste (né quella indicata né quella indovinata)."""
    if condition_type not in _TIPI_VALIDI:
        return None
    nome_tabella = trova_tabella_per_nome(connection_string, termine)
    if not nome_tabella:
        return None

    colonne, pk = _colonne_e_pk(connection_string, nome_tabella)
    nomi_reali = {c["name"] for c in colonne}

    if condition_type == "scadenza_superata":
        col = colonna_data if colonna_data in nomi_reali else analisi_automatica.colonna_data_plausibile(colonne)
        if not col:
            return None
        config: dict[str, Any] = {"colonna_data": col, "giorni_tolleranza": giorni_tolleranza}
    elif condition_type == "soglia_numerica":
        col = colonna if colonna in nomi_reali else analisi_automatica.colonna_numerica_plausibile(colonne, pk)
        if not col or operatore not in (">", "<") or soglia is None:
            return None
        config = {"colonna": col, "operatore": operatore, "soglia": soglia}
    else:  # valore_anomalo
        col = colonna if colonna in nomi_reali else analisi_automatica.colonna_numerica_plausibile(colonne, pk)
        if not col:
            return None
        config = {"colonna": col, "soglia_deviazioni": soglia_deviazioni}
        if colonna_gruppo in nomi_reali:
            config["colonna_gruppo"] = colonna_gruppo

    nome_regola = _nome_regola(nome_tabella, condition_type, config)
    regola, creata_ora = _trova_o_crea(db, integration, nome_tabella, condition_type, nome_regola, config)
    scattate = _valuta_ora(integration, nome_tabella, condition_type, json.loads(regola.config))
    return regola, creata_ora, scattate


def crea_o_riusa_segnalazione_scadenza(
    db: Session, integration: Integration, connection_string: str, termine: str, giorni_tolleranza: int = 0
) -> tuple[AlertRule, bool, list[dict[str, Any]]] | None:
    """Ripiego per StubLLMClient (nessun ragionamento, solo parole chiave —
    vedi llm_client._AVVISO_WORDS/_SCADENZA_WORDS): thin wrapper della
    funzione generica sopra, fissato su "scadenza_superata" perché è
    l'unico tipo abbastanza riconoscibile da un'espressione regolare."""
    return crea_o_riusa_segnalazione(
        db, integration, connection_string, termine, "scadenza_superata", giorni_tolleranza=giorni_tolleranza
    )


def crea_o_riusa_segnalazione_soglia(
    db: Session, integration: Integration, connection_string: str, termine: str, operatore: str, soglia: float
) -> tuple[AlertRule, bool, list[dict[str, Any]]] | None:
    """Come sopra ma per "soglia_numerica" (vedi llm_client._SOGLIA_RE)."""
    return crea_o_riusa_segnalazione(
        db, integration, connection_string, termine, "soglia_numerica", operatore=operatore, soglia=soglia
    )
