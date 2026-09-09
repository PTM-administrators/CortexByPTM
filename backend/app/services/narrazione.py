"""
Spiegazioni automatiche degli scostamenti: non solo "le spese sono salite",
ma perché — quale voce ha guidato il cambiamento, confrontato col periodo
precedente. Richiesta esplicita dell'utente il 18 agosto 2026 ("serve altro
di innovativo" — le notifiche automatiche da sole restavano solo un altro
modo di mostrare gli stessi numeri).

Nessun LLM: regole + un template scritto a mano sui dati che Cortex calcola
già (compute_spese_per_categoria) — gratuito e verificabile come il resto
del motore contabile, non un riassunto generato da un modello linguistico.

Generico per entrambi i profili: sia accounting_engine (Sampeyre) sia
accounting_engine_arca espongono la stessa `compute_spese_per_categoria`,
quindi questo modulo non sa (e non deve sapere) quale dei due sta usando —
il chiamante decide il motore, esattamente come già fa
agent_brain._handle_visualize per i grafici.
"""
from datetime import date
from typing import Any, Protocol

MESI_IT = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)

_SOGLIA_RILEVANZA = 0.01  # sotto un centesimo di differenza non è uno scostamento, è un arrotondamento


class _MotoreContabile(Protocol):
    def compute_spese_per_categoria(
        self, connection_string: str, anno: int, mese: int, tipo: str
    ) -> list[dict[str, Any]]: ...

    def ultimo_periodo_con_movimenti(self, connection_string: str) -> tuple[int, int] | None: ...


def _mese_precedente(anno: int, mese: int) -> tuple[int, int]:
    return (anno - 1, 12) if mese == 1 else (anno, mese - 1)


def _nome_periodo(anno: int, mese: int) -> str:
    return f"{MESI_IT[mese - 1].capitalize()} {anno}"


def _fmt_euro(valore: float) -> str:
    return f"{valore:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _scostamenti_per_voce(attuale: list[dict], precedente: list[dict]) -> list[dict[str, Any]]:
    """Unione delle voci presenti in uno dei due periodi (o entrambi), con
    il delta — una voce comparsa solo ora ha precedente=0, una sparita ha
    attuale=0, non sono casi speciali da escludere ma gli scostamenti più
    interessanti da segnalare."""
    mappa_precedente = {c["categoria_codice"]: c for c in precedente}
    codici_visti = set()
    risultati = []
    for c in attuale:
        codici_visti.add(c["categoria_codice"])
        prec = mappa_precedente.get(c["categoria_codice"])
        valore_prec = prec["totale"] if prec else 0.0
        risultati.append({"nome": c["nome"], "attuale": c["totale"], "precedente": valore_prec, "delta": c["totale"] - valore_prec})
    for c in precedente:
        if c["categoria_codice"] in codici_visti:
            continue
        risultati.append({"nome": c["nome"], "attuale": 0.0, "precedente": c["totale"], "delta": -c["totale"]})
    risultati.sort(key=lambda s: abs(s["delta"]), reverse=True)
    return [s for s in risultati if abs(s["delta"]) >= _SOGLIA_RILEVANZA]


def _frase_voce(s: dict[str, Any]) -> str:
    if s["precedente"] == 0:
        return f"è comparsa la voce \"{s['nome']}\" ({_fmt_euro(s['attuale'])}, non presente nel periodo precedente)"
    if s["attuale"] == 0:
        return f"non ci sono più movimenti in \"{s['nome']}\" (era {_fmt_euro(s['precedente'])})"
    verso = "aumentata" if s["delta"] > 0 else "diminuita"
    return f"\"{s['nome']}\" è {verso} di {_fmt_euro(abs(s['delta']))} (da {_fmt_euro(s['precedente'])} a {_fmt_euro(s['attuale'])})"


def _componi_narrazione(
    parola_tipo: str, nome_periodo: str, nome_periodo_prec: str, tot: float, tot_prec: float, principali: list[dict]
) -> str:
    delta_totale = tot - tot_prec
    if abs(delta_totale) < _SOGLIA_RILEVANZA:
        return f"Le {parola_tipo} di {nome_periodo} sono rimaste stabili rispetto a {nome_periodo_prec} ({_fmt_euro(tot)})."

    verso = "aumentate" if delta_totale > 0 else "diminuite"
    delta_perc = f" ({abs(delta_totale) / tot_prec * 100:.0f}%)" if tot_prec else ""
    intro = (
        f"Le {parola_tipo} di {nome_periodo} sono {verso} di {_fmt_euro(abs(delta_totale))}{delta_perc} "
        f"rispetto a {nome_periodo_prec} (da {_fmt_euro(tot_prec)} a {_fmt_euro(tot)})."
    )
    if not principali:
        return intro

    frasi = [_frase_voce(s) for s in principali[:3]]
    if len(frasi) == 1:
        motivo = frasi[0]
    else:
        # "ed" davanti a vocale (es. "ed è comparsa"), non solo per estetica:
        # "e è" è percepito come un errore da un lettore italiano.
        congiunzione = "ed" if frasi[-1][:1].lower() in "aeiouàèéìòù" else "e"
        motivo = "; ".join(frasi[:-1]) + f"; {congiunzione} {frasi[-1]}"
    return f"{intro} Il motivo principale: {motivo}."


def spiega_scostamento(motore: _MotoreContabile, connection_string: str, anno: int, mese: int, tipo: str = "uscita") -> dict[str, Any]:
    """Confronta il periodo richiesto con quello immediatamente precedente e
    spiega in linguaggio naturale cosa è cambiato — non solo il totale, le
    voci che hanno inciso di più."""
    anno_prec, mese_prec = _mese_precedente(anno, mese)
    attuale = motore.compute_spese_per_categoria(connection_string, anno, mese, tipo)
    precedente = motore.compute_spese_per_categoria(connection_string, anno_prec, mese_prec, tipo)

    tot = round(sum(c["totale"] for c in attuale), 2)
    tot_prec = round(sum(c["totale"] for c in precedente), 2)
    scostamenti = _scostamenti_per_voce(attuale, precedente)
    parola_tipo = "entrate" if tipo == "entrata" else "spese"

    return {
        "periodo": _nome_periodo(anno, mese),
        "periodo_precedente": _nome_periodo(anno_prec, mese_prec),
        "tipo": tipo,
        "totale": tot,
        "totale_precedente": tot_prec,
        "delta": round(tot - tot_prec, 2),
        "delta_percentuale": round((tot - tot_prec) / tot_prec * 100, 1) if tot_prec else None,
        "voci_principali": scostamenti[:5],
        "narrazione": _componi_narrazione(parola_tipo, _nome_periodo(anno, mese), _nome_periodo(anno_prec, mese_prec), tot, tot_prec, scostamenti),
    }


def spiega_ultimo_periodo_con_dati(motore: _MotoreContabile, connection_string: str, tipo: str = "uscita") -> dict[str, Any]:
    """Come spiega_scostamento, ma sul mese più recente che ha davvero
    movimenti registrati invece che sul mese di calendario corrente —
    usata dalla Dashboard (un riepilogo automatico, nessuna domanda esplicita
    dell'utente su "questo mese"). Un'azienda la cui ultima registrazione
    contabile non è recentissima (contabilità aggiornata in ritardo, o un
    database dimostrativo che si ferma a un anno passato) altrimenti
    confronterebbe sempre due mesi vuoti, mostrando "nessun cambiamento"
    quando in realtà esistono dati, solo non recenti. Un comando esplicito
    in chat ("le spese di questo mese") continua invece a usare il mese di
    calendario vero — lì l'utente ha chiesto proprio quello."""
    periodo = motore.ultimo_periodo_con_movimenti(connection_string)
    anno, mese = periodo if periodo else (date.today().year, date.today().month)
    return spiega_scostamento(motore, connection_string, anno, mese, tipo)
