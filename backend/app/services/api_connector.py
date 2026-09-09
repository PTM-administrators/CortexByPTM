"""
Motore generico per sorgenti dati esposte via API REST — parallelo a
data_explorer.py, ma per HTTP invece che per SQL. Stessa idea: qualunque
azienda collega la propria API (annunci, prodotti, prenotazioni...) definendo
solo URL e autenticazione, senza che serva scrivere codice per quel caso
specifico.

Differenza importante rispetto a un database: una riga di una tabella È già
tutta l'informazione disponibile. Una API invece tipicamente restituisce
nell'elenco solo un sottoinsieme di campi (per restare leggero) e riserva
l'informazione completa a un endpoint di dettaglio per singolo elemento —
esattamente come un portale di annunci mostra titolo/prezzo nell'elenco e
tutti i dettagli aprendo il singolo annuncio. Per questo get_row(), quando è
configurato un detail_path_template, richiama l'endpoint di dettaglio invece
di limitarsi ai campi già visti nell'elenco: è quello che permette a una
scheda di "espandersi" mostrando molte più informazioni di quelle usate per
titolo/prezzo/badge.

Configurazione attesa (credenziali dell'Integration, provider "rest_api"):
- base_url: es. "https://api.esempio.it"
- list_path: percorso (+ eventuale query string) dell'elenco, es. "/v1/annunci"
- list_items_path: percorso puntato dell'array dentro la risposta JSON, es.
  "results" o "data.items" — vuoto se la risposta STESSA è l'array
- id_field: campo usato come identificatore univoco, es. "id"
- detail_path_template: percorso del dettaglio con "{id}" come segnaposto,
  es. "/v1/annunci/{id}" — opzionale: se assente, l'espansione di una riga si
  limita ai campi già visti nell'elenco (onesto, non un errore)
- auth_header / auth_value: se entrambi presenti, inviati come header su ogni
  chiamata (es. auth_header="Authorization", auth_value="Bearer xxxx") — copre
  API-key e bearer token, non OAuth: per il resto va collegato un provider
  dedicato quando servirà davvero.
"""
from typing import Any

import requests

TIMEOUT_SECONDI = 10  # un'API esterna lenta o giù non deve bloccare la richiesta
_TABELLA_UNICA = "dati"  # pseudo-nome di tabella: un'integrazione API espone una sola risorsa


def _percorso_annidato(payload: Any, percorso: str) -> Any:
    if not percorso:
        return payload
    corrente = payload
    for chiave in percorso.split("."):
        if isinstance(corrente, dict):
            corrente = corrente.get(chiave)
        else:
            return None
    return corrente


def _header_auth(config: dict[str, Any]) -> dict[str, str]:
    header = (config.get("auth_header") or "").strip()
    valore = (config.get("auth_value") or "").strip()
    return {header: valore} if header and valore else {}


def _url_completo(config: dict[str, Any], percorso: str) -> str:
    base = (config.get("base_url") or "").rstrip("/")
    if not percorso:
        return base
    return f"{base}/{percorso.lstrip('/')}"


def _scarica_elenco(config: dict[str, Any]) -> list[dict[str, Any]]:
    url = _url_completo(config, config.get("list_path", ""))
    if not url:
        raise ValueError("Questa integrazione non ha un indirizzo API configurato")
    risposta = requests.get(url, headers=_header_auth(config), timeout=TIMEOUT_SECONDI)
    risposta.raise_for_status()
    elementi = _percorso_annidato(risposta.json(), config.get("list_items_path", ""))
    if not isinstance(elementi, list):
        raise ValueError(
            f"La risposta dell'API non contiene un elenco al percorso "
            f"'{config.get('list_items_path') or '(radice)'}'"
        )
    return [e for e in elementi if isinstance(e, dict)]


def list_tables(config: dict[str, Any]) -> list[str]:
    """Un'integrazione API espone una sola risorsa: un'unica pseudo-tabella,
    così il resto del sistema (Viste, Data Explorer) continua a funzionare
    senza dover distinguere 'tabella SQL' da 'risorsa API'."""
    return [_TABELLA_UNICA]


def get_table_schema(config: dict[str, Any], table_name: str) -> list[dict[str, Any]]:
    elementi = _scarica_elenco(config)
    if not elementi:
        return []
    # Le colonne sono i campi visti nel primo elemento: onesto, non tutte le
    # API garantiscono lo stesso schema riga per riga (a differenza di SQL).
    primo = elementi[0]
    id_field = config.get("id_field") or "id"
    return [
        {"name": chiave, "type": type(valore).__name__, "nullable": True, "primary_key": chiave == id_field}
        for chiave, valore in primo.items()
    ]


def list_rows(config: dict[str, Any], table_name: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    elementi = _scarica_elenco(config)
    pk = config.get("id_field") or "id"
    pagina = elementi[offset : offset + limit]
    colonne = list(pagina[0].keys()) if pagina else (list(elementi[0].keys()) if elementi else [])
    return {"columns": colonne, "primary_key": pk, "rows": pagina, "total": len(elementi)}


def get_row(config: dict[str, Any], table_name: str, pk_value: Any) -> dict[str, Any] | None:
    """Dettaglio di un singolo elemento — usa l'endpoint di dettaglio se
    configurato (più campi di quelli visti nell'elenco), altrimenti ripiega
    sull'elemento già visto nell'elenco."""
    pk = config.get("id_field") or "id"
    template = (config.get("detail_path_template") or "").strip()
    if template:
        url = _url_completo(config, template.replace("{id}", str(pk_value)))
        try:
            risposta = requests.get(url, headers=_header_auth(config), timeout=TIMEOUT_SECONDI)
            risposta.raise_for_status()
            dettaglio = risposta.json()
            if isinstance(dettaglio, dict):
                return dettaglio
        except requests.RequestException:
            pass  # ripiega sull'elenco sotto invece di far fallire l'intera richiesta

    for elemento in _scarica_elenco(config):
        if str(elemento.get(pk)) == str(pk_value):
            return elemento
    return None
