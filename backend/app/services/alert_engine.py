"""
Motore di segnalazioni proattive: regole deterministiche e gratuite (nessun
LLM) che l'agente valuta da solo sui dati collegati, per notare cose che
altrimenti l'utente dovrebbe accorgersi di chiedere — una scadenza superata,
un importo fuori soglia, un valore anomalo rispetto agli altri. Generico per
qualunque settore: la stessa regola "scadenza superata" serve per un
pagamento di un debitore o per la scadenza di un contratto, la stessa
"valore anomalo" per una spesa o per un prezzo — la regola non sa nulla del
significato dei dati, solo della loro forma (una data, un numero).

Gira sulla stessa sorgente dati generica delle Viste salvate (vedi
app.services.data_source) — database o API, indifferentemente.

Tre tipi di condizione, tenuti volutamente semplici perché restano gratuiti
e verificabili (una funzione pura, non un modello statistico complesso):

- "scadenza_superata": una colonna data è nel passato oltre una tolleranza.
- "soglia_numerica": una colonna numerica supera (o è sotto) un valore fisso.
- "valore_anomalo": una colonna numerica si scosta dalla media (del gruppo,
  se ne è indicata una colonna) più di N deviazioni standard — la stessa
  idea di "spesa anomala" dell'idea originale, senza servire un LLM.
"""
import json
from datetime import date
from statistics import mean, pstdev
from typing import Any

from sqlalchemy.orm import Session

from app.models.alert_rule import AlertRule
from app.models.integrations import Integration
from app.services import data_source
from app.services.data_source import DataSource
from app.services.templating import applica_template

LIMITE_RIGHE = 500  # come le Viste: basta per una valutazione utile, non l'intera tabella
_MINIMO_CAMPIONE = 4  # sotto questa soglia una media/deviazione non è affidabile

_TIPI_VALIDI = ("scadenza_superata", "soglia_numerica", "valore_anomalo")


def _a_data(valore: Any) -> date | None:
    if valore in (None, ""):
        return None
    try:
        return date.fromisoformat(str(valore)[:10])
    except ValueError:
        return None


def _a_numero(valore: Any) -> float | None:
    if valore in (None, ""):
        return None
    try:
        return float(valore)
    except (TypeError, ValueError):
        return None


def _valuta_scadenza_superata(righe: list[dict], config: dict) -> list[dict]:
    colonna = config.get("colonna_data")
    tolleranza = int(_a_numero(config.get("giorni_tolleranza")) or 0)
    oggi = date.today()
    risultati = []
    for riga in righe:
        scadenza = _a_data(riga.get(colonna))
        if scadenza is None:
            continue
        giorni_ritardo = (oggi - scadenza).days - tolleranza
        if giorni_ritardo > 0:
            risultati.append({"riga": riga, "dettaglio": f"scaduta da {giorni_ritardo} giorni"})
    return risultati


_CONFRONTI = {
    ">": lambda v, s: v > s,
    "<": lambda v, s: v < s,
    ">=": lambda v, s: v >= s,
    "<=": lambda v, s: v <= s,
}


def _valuta_soglia_numerica(righe: list[dict], config: dict) -> list[dict]:
    colonna = config.get("colonna")
    operatore = config.get("operatore", ">")
    soglia = _a_numero(config.get("soglia"))
    confronto = _CONFRONTI.get(operatore)
    if soglia is None or confronto is None:
        return []
    risultati = []
    for riga in righe:
        valore = _a_numero(riga.get(colonna))
        if valore is None:
            continue
        if confronto(valore, soglia):
            risultati.append({"riga": riga, "dettaglio": f"{colonna} = {valore:g} ({operatore} {soglia:g})"})
    return risultati


def _valuta_valore_anomalo(righe: list[dict], config: dict) -> list[dict]:
    colonna = config.get("colonna")
    colonna_gruppo = config.get("colonna_gruppo") or None
    soglia_deviazioni = _a_numero(config.get("soglia_deviazioni")) or 2.0

    gruppi: dict[Any, list[tuple[dict, float]]] = {}
    for riga in righe:
        valore = _a_numero(riga.get(colonna))
        if valore is None:
            continue
        chiave_gruppo = riga.get(colonna_gruppo) if colonna_gruppo else "_tutti_"
        gruppi.setdefault(chiave_gruppo, []).append((riga, valore))

    risultati = []
    for coppie in gruppi.values():
        if len(coppie) < _MINIMO_CAMPIONE:
            continue  # troppo pochi dati per una media/deviazione significativa
        valori = [v for _, v in coppie]
        media = mean(valori)
        deviazione = pstdev(valori)
        if deviazione == 0:
            continue  # tutti uguali: nessuno scarto è possibile
        for riga, valore in coppie:
            scarto = abs(valore - media) / deviazione
            if scarto >= soglia_deviazioni:
                risultati.append(
                    {
                        "riga": riga,
                        "dettaglio": f"{colonna} = {valore:g}, media {media:.2f} (scarto {scarto:.1f}x la deviazione standard)",
                    }
                )
    return risultati


_VALUTATORI = {
    "scadenza_superata": _valuta_scadenza_superata,
    "soglia_numerica": _valuta_soglia_numerica,
    "valore_anomalo": _valuta_valore_anomalo,
}


def valuta_condizione(condition_type: str, righe: list[dict], config: dict) -> list[dict[str, Any]]:
    """La sola condizione (senza bisogno di una AlertRule già salvata) — usata
    per l'anteprima live in fase di configurazione (vedi POST
    /alerts/anteprima): quante righe scatterebbero ORA con questi criteri,
    prima ancora di salvare la regola. Configurare una Segnalazione alla
    cieca (salva, poi vai a controllare altrove se funziona) era il punto
    più difficile segnalato dall'utente — questo chiude il giro subito."""
    valutatore = _VALUTATORI.get(condition_type)
    if valutatore is None:
        return []
    return valutatore(righe, config)


def valuta_regola_con_riga(rule: AlertRule, source: DataSource) -> list[dict[str, Any]]:
    """Come valuta_regola, ma include anche la riga intera (non solo pk e
    messaggio già formattato) — serve a chi deve costruire qualcosa dai
    valori reali della riga (es. un sollecito con {{email}}/{{importo}}),
    non solo mostrare un messaggio già pronto a un umano. `valuta_regola`
    resta la versione pubblica (usata da GET /alerts/segnalazioni) e si
    appoggia su questa togliendo "riga" — stessa valutazione, un solo posto
    che la fa davvero."""
    valutatore = _VALUTATORI.get(rule.condition_type)
    if valutatore is None:
        return []

    config = json.loads(rule.config)
    risultato = data_source.list_rows(source, rule.table_name, limit=LIMITE_RIGHE, offset=0)
    righe, pk = risultato["rows"], risultato["primary_key"]

    segnalazioni = []
    for grezzo in valutatore(righe, config):
        riga = grezzo["riga"]
        messaggio = applica_template(rule.messaggio_template, riga).strip() or grezzo["dettaglio"]
        segnalazioni.append(
            {
                "regola_id": rule.id,
                "regola_nome": rule.name,
                "pk": riga.get(pk),
                "messaggio": messaggio,
                "dettaglio": grezzo["dettaglio"],
                "riga": riga,
            }
        )
    return segnalazioni


def valuta_regola(rule: AlertRule, source: DataSource) -> list[dict[str, Any]]:
    """Righe della tabella collegata che violano la regola, con un messaggio
    già pronto da mostrare (il template dell'utente se configurato, altrimenti
    la descrizione tecnica generata dalla condizione) — senza la riga intera,
    non serve a chi deve solo mostrarle a un umano (vedi
    valuta_regola_con_riga per chi invece deve costruirci qualcosa)."""
    return [{k: v for k, v in s.items() if k != "riga"} for s in valuta_regola_con_riga(rule, source)]


def valuta_tutte_le_regole(db: Session, organization_id: int) -> list[dict[str, Any]]:
    """Tutte le segnalazioni attualmente attive per un'azienda — usata sia da
    GET /alerts/segnalazioni sia dal riepilogo multi-azienda (Portfolio,
    api/dashboard.py) e dal ciclo automatico (services/notifiche.py):
    stessa valutazione, un solo posto invece di reimplementarla ad ogni
    chiamante."""
    regole = db.query(AlertRule).filter(AlertRule.organization_id == organization_id, AlertRule.attiva.is_(True)).all()
    segnalazioni: list[dict[str, Any]] = []
    for regola in regole:
        integrazione = db.get(Integration, regola.integration_id)
        if integrazione is None:
            continue
        try:
            source = data_source.resolve(integrazione)
            grezze = valuta_regola(regola, source)
        except Exception:
            continue  # una sorgente irraggiungibile ora non deve bloccare le altre regole
        segnalazioni.extend(grezze)
    return segnalazioni
