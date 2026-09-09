"""
Motore di calcolo contabile per il template "nonprofit_accounting" (Fase C del
piano di progetto): saldi, ammortamenti, IVA, controllo budget, anomalie e
bilancio semplificato.

A differenza del Data Explorer (app.services.data_explorer), che è generico per
qualunque schema, questa è logica di dominio della finanza no-profit — resta
specifica di quel settore, esattamente come industry_rules.py distingue gli
altri. Un'azienda e-commerce avrà un motore diverso, non questo.

Tutti i calcoli sono interni, nessun servizio IA a pagamento coinvolto: coerente
con la Sezione 7 del piano di progetto, che riserva l'IA solo alle funzioni che
richiedono davvero comprensione del linguaggio (lettura documenti, assistente
conversazionale, bilanci commentati — Fase D).

Attenzione: il bilancio prodotto qui è un raggruppamento per categoria pensato
per essere utile e leggibile, non ancora il formato ufficiale (art. 2425 c.c.)
depositabile — le voci esatte di quel formato sono un punto esplicitamente
ancora da validare col commercialista (Sezione 11 del piano di progetto).
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from statistics import mean, pstdev
from typing import Any

from sqlalchemy import Table, select

from app.services import db_engine

CONTI = ("Banca", "Cassa", "Titoli")


def _engine(connection_string: str):
    # Engine + reflection cacheati (vedi app.services.db_engine) invece di
    # aprirne uno nuovo ad ogni chiamata — stesso beneficio già misurato per
    # il profilo Arca, qui applicato per coerenza anche se lo schema di
    # Sampeyre (poche tabelle, poche colonne) rendeva il problema meno grave.
    return db_engine.get_engine(connection_string)


def _reflect(engine: Any, table_name: str) -> Table:
    return db_engine.get_reflected_table(engine, table_name)


def _fetch_all(engine: Any, table: Table) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(select(table))]


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _categorie_tipo_map(engine: Any) -> dict[str, str]:
    """{codice_categoria: tipo}, tipo in entrata|uscita|cespite|patrimoniale."""
    categorie = _reflect(engine, "categorie")
    return {row["codice"]: row["tipo"] for row in _fetch_all(engine, categorie)}


def compute_saldi(connection_string: str) -> dict[str, float]:
    """Saldo attuale di Banca/Cassa/Titoli: le entrate sommano, tutto il resto
    (uscite, acquisti di cespiti, movimenti patrimoniali) sottrae — è denaro
    che è comunque uscito dal conto, a prescindere da come viene poi
    classificato nel Conto Economico."""
    engine = _engine(connection_string)
    movimenti = _reflect(engine, "movimenti")
    tipo_map = _categorie_tipo_map(engine)
    saldi: dict[str, Decimal] = {conto: Decimal("0") for conto in CONTI}

    for row in _fetch_all(engine, movimenti):
        conto = row["conto"]
        saldi.setdefault(conto, Decimal("0"))
        importo = _as_decimal(row["importo"])
        tipo = tipo_map.get(row["categoria_codice"], "uscita")
        saldi[conto] += importo if tipo == "entrata" else -importo

    return {conto: float(saldo) for conto, saldo in saldi.items()}


def compute_ammortamenti(connection_string: str, anno: int) -> list[dict[str, Any]]:
    """Quota di ammortamento annuale per ogni Cespite posseduto in quell'anno
    (dall'anno di acquisto compreso in poi). Calcolo lineare semplice
    (costo × aliquota%, stessa quota ogni anno), senza pro-rata sui mesi: un
    primo modello, da raffinare se serve più precisione fiscale."""
    engine = _engine(connection_string)
    cespiti = _reflect(engine, "cespiti")
    risultati = []
    for row in _fetch_all(engine, cespiti):
        anno_acquisto = _as_date(row["data_acquisto"]).year
        if anno_acquisto > anno:
            continue
        costo = _as_decimal(row["costo"])
        aliquota = _as_decimal(row["aliquota_ammortamento"])
        quota = (costo * aliquota / Decimal("100")).quantize(Decimal("0.01"))
        risultati.append(
            {
                "cespite_id": row["id"],
                "descrizione": row["descrizione"],
                "categoria_codice": row["categoria_codice"],
                "anno_acquisto": anno_acquisto,
                "quota_annuale": float(quota),
            }
        )
    return risultati


def compute_iva(connection_string: str, anno: int) -> dict[str, float]:
    """IVA a debito (incassata sulle entrate, da versare) e a credito (pagata
    sugli acquisti, recuperabile) per l'anno indicato. Il pro-rata di
    detraibilità (Sezione 11 del piano di progetto) non è ancora applicato:
    va confermato col commercialista prima di introdurlo."""
    engine = _engine(connection_string)
    movimenti = _reflect(engine, "movimenti")
    tipo_map = _categorie_tipo_map(engine)
    a_debito = Decimal("0")
    a_credito = Decimal("0")

    for row in _fetch_all(engine, movimenti):
        if row["iva"] is None:
            continue
        if _as_date(row["data"]).year != anno:
            continue
        iva = _as_decimal(row["iva"])
        tipo = tipo_map.get(row["categoria_codice"], "uscita")
        if tipo == "entrata":
            a_debito += iva
        elif tipo == "uscita":
            a_credito += iva

    return {
        "iva_a_debito": float(a_debito),
        "iva_a_credito": float(a_credito),
        "saldo_iva": float(a_debito - a_credito),
    }


def check_budget(connection_string: str, anno: int, mese: int) -> list[dict[str, Any]]:
    """Confronta la spesa del mese con le soglie impostate in soglie_budget."""
    engine = _engine(connection_string)
    movimenti = _reflect(engine, "movimenti")
    soglie = _reflect(engine, "soglie_budget")

    spesa_per_categoria: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in _fetch_all(engine, movimenti):
        data_mov = _as_date(row["data"])
        if data_mov.year == anno and data_mov.month == mese:
            spesa_per_categoria[row["categoria_codice"]] += _as_decimal(row["importo"])

    risultati = []
    for soglia in _fetch_all(engine, soglie):
        codice = soglia["categoria_codice"]
        speso = spesa_per_categoria.get(codice, Decimal("0"))
        limite = _as_decimal(soglia["soglia_mensile"])
        percentuale = float(speso / limite * 100) if limite else 0.0
        if speso > limite:
            livello = "superato"
        elif percentuale >= 80:
            livello = "in avvicinamento"
        else:
            livello = "ok"
        risultati.append(
            {
                "categoria_codice": codice,
                "speso": float(speso),
                "soglia_mensile": float(limite),
                "percentuale": round(percentuale, 1),
                "livello": livello,
            }
        )
    return risultati


def detect_anomalie(connection_string: str, mesi_storico: int = 6) -> list[dict[str, Any]]:
    """Per ogni categoria di uscita, confronta la spesa del mese corrente con la
    media dei mesi precedenti disponibili e segnala uno scostamento marcato
    (z-score >= 2) — statistica descrittiva, nessun servizio IA coinvolto."""
    engine = _engine(connection_string)
    movimenti = _reflect(engine, "movimenti")
    tipo_map = _categorie_tipo_map(engine)
    oggi = date.today()
    mese_corrente = (oggi.year, oggi.month)

    per_categoria_mese: dict[str, dict[tuple[int, int], Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )
    for row in _fetch_all(engine, movimenti):
        codice = row["categoria_codice"]
        if tipo_map.get(codice) != "uscita":
            continue
        data_mov = _as_date(row["data"])
        per_categoria_mese[codice][(data_mov.year, data_mov.month)] += _as_decimal(row["importo"])

    anomalie = []
    for codice, mesi in per_categoria_mese.items():
        corrente = float(mesi.get(mese_corrente, Decimal("0")))
        storico_completo = sorted((k, v) for k, v in mesi.items() if k != mese_corrente)
        storico = [float(v) for _, v in storico_completo[-mesi_storico:]]
        if len(storico) < 2:
            continue  # troppo pochi mesi di storico per giudicare un'anomalia
        media = mean(storico)
        dev_std = pstdev(storico)
        if dev_std == 0:
            continue
        z_score = (corrente - media) / dev_std
        if abs(z_score) >= 2:
            anomalie.append(
                {
                    "categoria_codice": codice,
                    "spesa_mese_corrente": round(corrente, 2),
                    "media_storica": round(media, 2),
                    "scostamento": round(z_score, 2),
                }
            )
    return anomalie


def compute_bilancio(connection_string: str, anno: int) -> dict[str, Any]:
    """Conto Economico e Stato Patrimoniale semplificati per l'anno indicato."""
    engine = _engine(connection_string)
    movimenti = _reflect(engine, "movimenti")
    categorie = _reflect(engine, "categorie")
    cat_info = {row["codice"]: row for row in _fetch_all(engine, categorie)}

    per_gruppo: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    totale_entrate = Decimal("0")
    totale_uscite = Decimal("0")

    for row in _fetch_all(engine, movimenti):
        if _as_date(row["data"]).year != anno:
            continue
        info = cat_info.get(row["categoria_codice"])
        tipo = info["tipo"] if info else "uscita"
        if tipo not in ("entrata", "uscita"):
            continue  # cespiti e movimenti patrimoniali non entrano nel Conto Economico
        importo = _as_decimal(row["importo"])
        gruppo = info["gruppo"] if info else "Non categorizzato"
        per_gruppo[gruppo] += importo if tipo == "entrata" else -importo
        if tipo == "entrata":
            totale_entrate += importo
        else:
            totale_uscite += importo

    ammortamenti = compute_ammortamenti(connection_string, anno)
    totale_ammortamenti = sum((Decimal(str(a["quota_annuale"])) for a in ammortamenti), Decimal("0"))
    totale_uscite += totale_ammortamenti

    saldi = compute_saldi(connection_string)

    cespiti = _reflect(engine, "cespiti")
    valore_netto_cespiti = Decimal("0")
    for row in _fetch_all(engine, cespiti):
        costo = _as_decimal(row["costo"])
        fondo = _as_decimal(row["fondo_ammortamento"] or 0)
        valore_netto_cespiti += costo - fondo

    return {
        "anno": anno,
        "conto_economico": {
            "per_gruppo": {k: float(v) for k, v in per_gruppo.items()},
            "totale_entrate": float(totale_entrate),
            "totale_uscite": float(totale_uscite),
            "totale_ammortamenti": float(totale_ammortamenti),
            "risultato": float(totale_entrate - totale_uscite),
        },
        "stato_patrimoniale_semplificato": {
            "liquidita": saldi,
            "totale_liquidita": float(sum(Decimal(str(v)) for v in saldi.values())),
            "immobilizzazioni_nette": float(valore_netto_cespiti),
        },
        "nota": (
            "Bilancio raggruppato per categoria, pensato per essere utile e leggibile "
            "subito: le voci esatte del formato ufficiale (art. 2425 c.c.) sono ancora "
            "da validare col commercialista, come indicato nella Sezione 11 del piano "
            "di progetto — non è ancora il formato depositabile."
        ),
    }


def compute_spese_per_categoria(
    connection_string: str, anno: int, mese: int, tipo: str = "uscita"
) -> list[dict[str, Any]]:
    """Totale movimenti di un mese raggruppati per categoria (nome + codice),
    filtrati per tipo (entrata|uscita). Usata dall'agente per rispondere a
    richieste come "mostrami le spese di luglio" con un grafico invece che
    solo testo (vedi llm_client.py / agent_brain.py)."""
    engine = _engine(connection_string)
    movimenti = _reflect(engine, "movimenti")
    categorie = _reflect(engine, "categorie")
    cat_info = {row["codice"]: row for row in _fetch_all(engine, categorie)}

    per_categoria: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in _fetch_all(engine, movimenti):
        data_mov = _as_date(row["data"])
        if data_mov.year != anno or data_mov.month != mese:
            continue
        info = cat_info.get(row["categoria_codice"])
        if info is None or info["tipo"] != tipo:
            continue
        per_categoria[row["categoria_codice"]] += _as_decimal(row["importo"])

    risultati = [
        {
            "categoria_codice": codice,
            "nome": cat_info[codice]["nome"],
            "totale": float(totale),
        }
        for codice, totale in per_categoria.items()
    ]
    risultati.sort(key=lambda r: r["totale"], reverse=True)
    return risultati


def list_movimenti(connection_string: str, anno: int, mese: int, tipo: str | None = None) -> list[dict[str, Any]]:
    """Righe grezze dei Movimenti di un mese (non aggregate), per la vista a
    tabella richiesta all'agente ("dammi l'elenco dei movimenti di luglio").
    `tipo` opzionale (entrata|uscita) filtra, altrimenti li mostra tutti."""
    engine = _engine(connection_string)
    movimenti = _reflect(engine, "movimenti")
    categorie = _reflect(engine, "categorie")
    cat_info = {row["codice"]: row for row in _fetch_all(engine, categorie)}

    righe = []
    for row in _fetch_all(engine, movimenti):
        data_mov = _as_date(row["data"])
        if data_mov.year != anno or data_mov.month != mese:
            continue
        info = cat_info.get(row["categoria_codice"])
        if tipo is not None and (info is None or info["tipo"] != tipo):
            continue
        righe.append(
            {
                "data": data_mov.isoformat(),
                "descrizione": row["descrizione"],
                "categoria": info["nome"] if info else row["categoria_codice"],
                "conto": row["conto"],
                "importo": float(_as_decimal(row["importo"])),
            }
        )
    righe.sort(key=lambda r: r["data"])
    return righe


# Pubblica (non prefissata da `_`): riusata anche da llm_client.py per
# riconoscere i nomi dei mesi nelle richieste di grafico in chat.
MESI_IT = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)


def compute_andamento_mensile(connection_string: str, anno: int, tipo: str = "uscita") -> list[dict[str, Any]]:
    """Totale movimenti di un tipo (entrata|uscita) per ciascuno dei 12 mesi
    dell'anno indicato — l'"andamento" richiesto all'agente con frasi come
    "come sono andate le spese nel 2026"."""
    engine = _engine(connection_string)
    movimenti = _reflect(engine, "movimenti")
    categorie = _reflect(engine, "categorie")
    tipo_map = {row["codice"]: row["tipo"] for row in _fetch_all(engine, categorie)}

    per_mese: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in _fetch_all(engine, movimenti):
        data_mov = _as_date(row["data"])
        if data_mov.year != anno or tipo_map.get(row["categoria_codice"]) != tipo:
            continue
        per_mese[data_mov.month] += _as_decimal(row["importo"])

    return [{"mese": m, "nome_mese": MESI_IT[m - 1], "totale": float(per_mese.get(m, Decimal("0")))} for m in range(1, 13)]


def ultimo_periodo_con_movimenti(connection_string: str) -> tuple[int, int] | None:
    """Anno e mese dell'ultimo movimento registrato — usato dalla Dashboard
    per "cosa è cambiato" a partire dall'ultima attività contabile reale
    invece che dal mese di calendario corrente: un'azienda la cui ultima
    registrazione non è recentissima (contabilità aggiornata in ritardo, o
    un database dimostrativo) altrimenti confronterebbe sempre due mesi
    vuoti, mostrando "nessun cambiamento" quando in realtà esistono dati.
    None se non c'è nessun movimento registrato."""
    engine = _engine(connection_string)
    movimenti = _reflect(engine, "movimenti")
    date_movimenti = [_as_date(row["data"]) for row in _fetch_all(engine, movimenti)]
    if not date_movimenti:
        return None
    ultima = max(date_movimenti)
    return (ultima.year, ultima.month)
