"""
Componenti visivi (widget e grafici) restituiti dall'agente operativo.
Estrazione dal file agent_brain.py per separare l'estetica dalla logica.
"""
from typing import Any
from app.services.accounting_engine import MESI_IT

def _titolo_metrica(tipo: str) -> str:
    return "Entrate" if tipo == "entrata" else "Spese"


def _nome_periodo(anno: int, mese: int) -> str:
    return f"{MESI_IT[mese - 1].capitalize()} {anno}"


_MAX_SEGMENTI_CATEGORIA = 8  # "token ceiling" della palette categorica (skill dataviz): oltre, si ripiega su "Altro"


def _fold_altro(dati: list[dict], max_segmenti: int = _MAX_SEGMENTI_CATEGORIA) -> list[dict]:
    """Oltre max_segmenti categorie, somma la coda in una voce "Altro" invece
    di continuare a generare colori: la palette categorica valida solo un
    numero fisso di tonalità (vedi skill dataviz, "token ceiling")."""
    if len(dati) <= max_segmenti:
        return dati
    principali = dati[: max_segmenti - 1]
    resto = dati[max_segmenti - 1 :]
    totale_resto = sum(d["totale"] for d in resto)
    return [*principali, {"categoria_codice": "altro", "nome": "Altro", "totale": totale_resto}]


def _chart_confronto(dati1: list[dict], dati2: list[dict], nome1: str, nome2: str, tipo: str) -> dict[str, Any]:
    mappa1 = {d["categoria_codice"]: d for d in dati1}
    mappa2 = {d["categoria_codice"]: d for d in dati2}
    codici = set(mappa1) | set(mappa2)
    codici_ordinati = sorted(
        codici, key=lambda c: max(mappa1.get(c, {}).get("totale", 0), mappa2.get(c, {}).get("totale", 0)), reverse=True
    )
    labels = [(mappa1.get(c) or mappa2.get(c))["nome"] for c in codici_ordinati]
    return {
        "type": "grouped_bar",
        "title": f"{_titolo_metrica(tipo)} per categoria — {nome1} vs {nome2}",
        "labels": labels,
        "series": [
            {"name": nome1, "data": [mappa1.get(c, {}).get("totale", 0) for c in codici_ordinati]},
            {"name": nome2, "data": [mappa2.get(c, {}).get("totale", 0) for c in codici_ordinati]},
        ],
    }


def _chart_periodo(dati: list[dict], nome_periodo: str, tipo: str) -> dict[str, Any]:
    return {
        "type": "bar",
        "title": f"{_titolo_metrica(tipo)} per categoria — {nome_periodo}",
        "labels": [d["nome"] for d in dati],
        "series": [{"name": nome_periodo, "data": [d["totale"] for d in dati]}],
    }


def _chart_composizione(dati: list[dict], nome_periodo: str, tipo: str) -> dict[str, Any]:
    """Parte-sul-tutto → barra impilata orizzontale (non una torta): con nomi
    di categoria lunghi la torta diventa illeggibile, la barra impilata resta
    leggibile e confrontabile (guida form-first della skill dataviz)."""
    dati_ripiegati = _fold_altro(dati)
    return {
        "type": "stacked_bar",
        "title": f"Composizione {_titolo_metrica(tipo).lower()} — {nome_periodo}",
        "labels": [nome_periodo],
        "series": [{"name": d["nome"], "data": [d["totale"]]} for d in dati_ripiegati],
    }


def _chart_andamento(dati: list[dict], anno: int, tipo: str) -> dict[str, Any]:
    return {
        "type": "line",
        "title": f"Andamento {_titolo_metrica(tipo).lower()} — {anno}",
        "labels": [d["nome_mese"].capitalize() for d in dati],
        "series": [{"name": "Totale", "data": [d["totale"] for d in dati]}],
    }


def _widget_saldo(saldi: dict[str, float]) -> dict[str, Any]:
    totale = sum(saldi.values())
    items = [{"label": conto, "value": valore, "format": "currency"} for conto, valore in saldi.items()]
    items.append({"label": "Totale", "value": totale, "format": "currency"})
    return {"type": "cards", "title": "Liquidità attuale", "items": items}


def _periodo_richiesto(args: dict[str, Any]) -> tuple[int, int]:
    """La coppia (anno, mese) del primo periodo richiesto, col mese corrente
    come ripiego se assente. StubLLMClient lo passa sempre per questi modi,
    ma un LLM vero (GeminiLLMClient/OpenAILLMClient) può legittimamente
    ometterlo se l'utente non ha specificato un mese — lo schema del tool
    non lo rende obbligatorio, solo "modo" lo è (vedi
    llm_client._function_declarations). Senza questo ripiego,
    args["periodi"][0] solleverebbe un KeyError poco chiaro invece di
    mostrare comunque qualcosa di sensato."""
    periodi = args.get("periodi")
    if periodi:
        anno, mese = periodi[0]
        return int(anno), int(mese)
    oggi = date.today()
    return oggi.year, oggi.month


def _widget_spiegazione(risultato: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "narrative",
        "title": f"Cosa è cambiato — {risultato['periodo']}",
        "text": risultato["narrazione"],
    }


def _widget_quadro_generale(
    saldi: dict[str, float], spiegazione: dict[str, Any], previsione_dati: dict[str, Any], segnalazioni: list[dict]
) -> dict[str, Any]:
    """Non un grafico singolo scelto da un menu fisso ma una vista
    d'insieme che combina più cose già calcolate altrove — liquidità, cosa
    è cambiato, previsione di cassa, segnalazioni aperte — nello stesso
    colpo, per una domanda aperta ("come sta andando l'azienda?") che non
    ha senso far entrare in uno solo dei modi esistenti (feedback
    dell'utente il 26 agosto 2026: i modi fissi sono "solo template già
    fatti"). Nessun calcolo nuovo: sola composizione di funzioni già
    verificate altrove (saldi, narrazione, previsione, segnalazioni)."""
    return {
        "type": "quadro_generale",
        "title": "Quadro generale dell'azienda",
        "liquidita": {"totale": round(sum(saldi.values()), 2), "saldi": saldi},
        "cosa_e_cambiato": spiegazione.get("narrazione", ""),
        "previsione": {
            "flusso_medio_mensile": previsione_dati.get("flusso_medio_mensile"),
            "proiezione": previsione_dati.get("proiezione", []),
            "avviso": previsione_dati.get("avviso"),
        },
        "segnalazioni_aperte": len(segnalazioni),
        "segnalazioni_esempi": [s["messaggio"] for s in segnalazioni[:3]],
    }


def _widget_elenco(righe: list[dict], nome_periodo: str) -> dict[str, Any]:
    return {
        "type": "table",
        "title": f"Movimenti — {nome_periodo}",
        "columns": [
            {"key": "data", "label": "Data"},
            {"key": "descrizione", "label": "Descrizione"},
            {"key": "categoria", "label": "Categoria"},
            {"key": "conto", "label": "Conto"},
            {"key": "importo", "label": "Importo"},
        ],
        "rows": righe,
    }


