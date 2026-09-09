"""
Previsione di cassa: proietta in avanti la liquidità attuale dal flusso netto
medio reale degli ultimi mesi — non uno strumento di ML, una proiezione
lineare semplice e verificabile sugli stessi dati che Cortex già legge per
bilancio/spiegazioni (compute_saldi, compute_spese_per_categoria), sullo
stesso principio "gratuito e trasparente" del resto del motore contabile
(vedi alert_engine.py, narrazione.py).

Richiesta dell'utente (26 agosto 2026): oggi Cortex mostra solo la
liquidità *attuale* — questa è la prima funzione che guarda avanti, per
avvisare prima che un problema di cassa diventi reale invece di scoprirlo
quando è già successo.

Generico per entrambi i profili come narrazione.py: non sa se sta leggendo
Sampeyre o Arca, riceve il motore giusto dal chiamante.
"""
from typing import Any, Protocol

MESI_IT = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)

_MESI_STORICO_DEFAULT = 6  # abbastanza per smussare un mese anomalo, non così tanti da annacquare un trend recente
_MESI_AVANTI_DEFAULT = 3


class _MotoreContabile(Protocol):
    def compute_saldi(self, connection_string: str) -> dict[str, float]: ...

    def compute_spese_per_categoria(
        self, connection_string: str, anno: int, mese: int, tipo: str
    ) -> list[dict[str, Any]]: ...

    def ultimo_periodo_con_movimenti(self, connection_string: str) -> tuple[int, int] | None: ...


def _mese_precedente(anno: int, mese: int) -> tuple[int, int]:
    return (anno - 1, 12) if mese == 1 else (anno, mese - 1)


def _mese_successivo(anno: int, mese: int) -> tuple[int, int]:
    return (anno + 1, 1) if mese == 12 else (anno, mese + 1)


def _nome_periodo(anno: int, mese: int) -> str:
    return f"{MESI_IT[mese - 1].capitalize()} {anno}"


def _fmt_euro(valore: float) -> str:
    return f"{valore:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _flusso_netto(motore: _MotoreContabile, connection_string: str, anno: int, mese: int) -> float:
    """Entrate meno uscite di un mese — lo stesso "flusso di cassa" che un
    titolare capisce a naso, ricavato sommando le due categorie già
    calcolate da compute_spese_per_categoria (nessun calcolo nuovo)."""
    entrate = sum(c["totale"] for c in motore.compute_spese_per_categoria(connection_string, anno, mese, "entrata"))
    uscite = sum(c["totale"] for c in motore.compute_spese_per_categoria(connection_string, anno, mese, "uscita"))
    return round(entrate - uscite, 2)


def previsione_liquidita(
    motore: _MotoreContabile,
    connection_string: str,
    mesi_storico: int = _MESI_STORICO_DEFAULT,
    mesi_avanti: int = _MESI_AVANTI_DEFAULT,
) -> dict[str, Any]:
    """Proietta la liquidità attuale per i prossimi `mesi_avanti` mesi,
    usando il flusso netto medio degli ultimi `mesi_storico` mesi con
    movimenti reali — a partire dall'ultima attività contabile vera, non dal
    mese di calendario corrente (stesso motivo di
    narrazione.spiega_ultimo_periodo_con_dati: un'azienda la cui contabilità
    si ferma a un anno fa altrimenti non avrebbe nessuno storico recente da
    cui proiettare)."""
    saldi = motore.compute_saldi(connection_string)
    liquidita_attuale = round(sum(saldi.values()), 2)

    periodo = motore.ultimo_periodo_con_movimenti(connection_string)
    if periodo is None:
        return {
            "liquidita_attuale": liquidita_attuale,
            "periodo_riferimento": None,
            "flusso_medio_mensile": None,
            "mesi_storico_usati": 0,
            "proiezione": [],
            "avviso": None,
            "narrazione": "Nessun movimento storico trovato: non è possibile stimare un andamento.",
        }

    anno, mese = periodo
    flussi = []
    a, m = anno, mese
    for _ in range(mesi_storico):
        flussi.append(_flusso_netto(motore, connection_string, a, m))
        a, m = _mese_precedente(a, m)
    flusso_medio = round(sum(flussi) / len(flussi), 2)

    proiezione = []
    liquidita_stimata = liquidita_attuale
    a, m = _mese_successivo(anno, mese)
    for _ in range(mesi_avanti):
        liquidita_stimata = round(liquidita_stimata + flusso_medio, 2)
        proiezione.append({"periodo": _nome_periodo(a, m), "liquidita_stimata": liquidita_stimata})
        a, m = _mese_successivo(a, m)

    sotto_zero = next((p for p in proiezione if p["liquidita_stimata"] < 0), None)

    verso = "positivo" if flusso_medio >= 0 else "negativo"
    narrazione = (
        f"Negli ultimi {len(flussi)} mesi con movimenti registrati (fino a {_nome_periodo(anno, mese)}), "
        f"il flusso di cassa netto medio è stato {verso}, {_fmt_euro(abs(flusso_medio))} al mese. "
        f"Proiettando questo ritmo, la liquidità stimata a {proiezione[-1]['periodo']} è "
        f"{_fmt_euro(proiezione[-1]['liquidita_stimata'])}."
    )
    avviso = None
    if sotto_zero:
        avviso = f"Al ritmo attuale, la liquidità stimata scenderebbe sotto zero a {sotto_zero['periodo']}."
        narrazione += f" Attenzione: {avviso[0].lower()}{avviso[1:]}"

    return {
        "liquidita_attuale": liquidita_attuale,
        "periodo_riferimento": _nome_periodo(anno, mese),
        "flusso_medio_mensile": flusso_medio,
        "mesi_storico_usati": len(flussi),
        "proiezione": proiezione,
        "avviso": avviso,
        "narrazione": narrazione,
    }
