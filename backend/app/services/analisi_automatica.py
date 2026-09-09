"""
Analisi automatica: per un database collegato qualunque — nessun profilo
contabile riconosciuto richiesto, funziona anche su uno schema mai visto
prima — scandaglia le tabelle e trova da sola quelle che hanno una colonna
data e una colonna numerica plausibili, mostrando un andamento mensile
senza che l'utente debba costruire una Vista o una Segnalazione.

Richiesta esplicita dell'utente (26 agosto 2026): "le viste e le
segnalazioni sono troppo difficili da programmare, Cortex deve essere un
software che lo fa in automatico". Non un configuratore più semplice (già
fatto: guess automatico delle colonne in Viste.jsx/Segnalazioni.jsx, ma
l'utente deve comunque cliccare "salva") — qui non c'è nessun passaggio
umano: ci si collega, e Cortex mostra già qualcosa.

Tre passaggi pensati per le performance, misurati su un database Arca
reale (372 tabelle):
1. Un COUNT(*) grezzo per tabella (query diretta, senza reflection — ~3s
   per tutte le 372) scarta le tabelle vuote o quasi: la maggior parte di
   un ERP reale sono tabelle di configurazione/lookup con poche righe.
2. Inspector.get_columns() sulle tabelle rimaste (~6s per tutte le 372,
   molto più leggero della reflection SQLAlchemy piena — quella misurata a
   16 secondi su una singola tabella larga, vedi services/db_engine.py):
   legge nomi e tipi di colonna senza costruire l'oggetto Table completo.
3. Solo le poche tabelle che hanno sia una colonna-tipo-data sia una
   colonna-tipo-numero vengono interrogate per i dati veri (le uniche a
   passare tramite la reflection piena, cacheata da db_engine.py — un
   numero piccolo, non le 372 di partenza).

Il risultato completo è cacheato con TTL (stesso principio di
services/db_engine.py): la scansione full costa qualche secondo la prima
volta, le visite successive sono istantanee.
"""
import threading
import time
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import column as sa_column
from sqlalchemy import inspect, select, table as sa_table, text

from app.services import db_engine

MESI_IT = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)

_SOGLIA_RIGHE_MINIMA = 5  # sotto, non c'è abbastanza dato per un andamento sensato
_LIMITE_TABELLE_MOSTRATE = 12  # le più "ricche" di righe, non tutte quelle che passano i filtri — pagina leggibile
_LIMITE_RIGHE_PER_TABELLA = 3000  # le righe più recenti, non l'intera storia di una tabella enorme
_MESI_MOSTRATI = 12
_TTL_SECONDI = 1800  # 30 minuti: la scansione full costa secondi, non va rifatta ad ogni apertura pagina

_INDIZI_DATA = ("data", "date", "scadenza", "giorno", "quando", "appuntamento", "dtreg", "registrazione")
_INDIZI_NUMERICI = ("importo", "prezzo", "totale", "quantita", "valore", "costo", "spesa", "somma", "amount")
_TIPI_DATA = ("DATE", "DATETIME", "TIMESTAMP")
_TIPI_NUMERICI = ("INT", "NUMERIC", "DECIMAL", "FLOAT", "REAL", "DOUBLE", "MONEY")

# Colonne data che esistono per audit interno (quando la riga è stata
# scritta/modificata nel database), non per il fatto contabile/di business
# che rappresentano — un "andamento" su queste rifletterebbe i tempi
# dell'inserimento dati, non l'attività reale dell'azienda. Scoperto
# provando su un database Arca reale: senza questa esclusione, tabelle
# come CGConto/CGBil (anagrafiche, non movimenti) venivano mostrate con un
# "andamento" costruito su TimeIns — un dato tecnico, non di business.
_NOMI_DATA_ESCLUSI = ("timeins", "timeupd", "createdat", "updatedat", "modifiedat", "lastmodified", "ts", "dataaggiornamento")

_lock = threading.Lock()
_cache: dict[str, tuple[list[dict[str, Any]], float]] = {}


def _e_tipo_data(tipo_sql: str) -> bool:
    return any(t in tipo_sql.upper() for t in _TIPI_DATA)


def _e_tipo_numerico(tipo_sql: str) -> bool:
    return any(t in tipo_sql.upper() for t in _TIPI_NUMERICI)


def _sembra_id(nome_colonna: str) -> bool:
    n = nome_colonna.lower()
    return n == "id" or n.startswith("id_") or n.endswith("_id") or n.endswith("id")


def _colonna_data(colonne: list[dict]) -> str | None:
    """Il TIPO SQL è un segnale affidabile (una colonna DATE/DATETIME lo è
    per costruzione) ma non basta da solo: molte tabelle hanno SOLO colonne
    di audit interno (TimeIns/TimeUpd, quando la riga è stata scritta nel
    database) e nessuna data "di business" — un andamento su quelle
    sarebbe un dato tecnico spacciato per attività reale. Se dopo aver
    escluso le colonne di audit non resta nessuna data, la tabella va
    saltata (return None), non ripiegata su una colonna comunque
    fuorviante."""
    candidate = [
        c for c in colonne
        if _e_tipo_data(str(c["type"])) and c["name"].lower() not in _NOMI_DATA_ESCLUSI
    ]
    if not candidate:
        return None
    per_nome = [c for c in candidate if any(p in c["name"].lower() for p in _INDIZI_DATA)]
    return (per_nome[0] if per_nome else candidate[0])["name"]


def _colonna_numerica(colonne: list[dict], colonne_pk: set[str]) -> str | None:
    """A differenza della data, qui NON basta il tipo SQL: una colonna
    INTEGER è tipicamente un codice, un flag o un indice di ordinamento
    (verificato su un database reale: "TipoConto", "Ordine", "Segno",
    "NumProtI" sono tutte INTEGER ma nessuna è un importo) — mostrarne
    l'andamento sarebbe rumore, non un dato utile. Richiede quindi un nome
    plausibile da _INDIZI_NUMERICI: meglio mostrare meno tabelle ma vere,
    che molte ma senza senso."""
    # Prefisso, non sottostringa: "ContoMerceSpesa" contiene "spesa" ma è un
    # flag (booleano "riga di spesa sì/no"), non un importo — scoperto
    # provando su dati reali, dove veniva scelta al posto della vera
    # colonna importo della stessa tabella (ImportoE). I nomi reali di un
    # importo iniziano quasi sempre con la parola (Importo/Prezzo/Totale...),
    # non la contengono in coda dopo un prefisso che ne cambia il significato.
    candidate = [
        c for c in colonne
        if _e_tipo_numerico(str(c["type"]))
        and c["name"] not in colonne_pk
        and not _sembra_id(c["name"])
        and c["name"].lower().startswith(_INDIZI_NUMERICI)
    ]
    if not candidate:
        return None
    # A parità di prefisso, il nome più corto è tipicamente il campo
    # "principale" (es. "Importo" preferito a "ImportoPartitaV", una
    # variante più specifica) — solo uno spareggio, non il criterio
    # primario, che resta il prefisso verificato sopra.
    candidate.sort(key=lambda c: len(c["name"]))
    return candidate[0]["name"]


def _conta_righe(engine: Any, nomi_tabelle: list[str]) -> dict[str, int]:
    """COUNT(*) diretto via SQL, non tramite un Table riflesso: molto più
    veloce, e qui serve solo un numero per scartare le tabelle vuote, non
    un oggetto Table completo. `nomi_tabelle` viene sempre da
    list_table_names() (whitelist reale del database), mai da input utente
    — l'interpolazione diretta nel nome tabella è sicura solo per questo."""
    conteggi: dict[str, int] = {}
    with engine.connect() as conn:
        for nome in nomi_tabelle:
            try:
                conteggi[nome] = conn.execute(text(f'SELECT COUNT(*) FROM "{nome}"')).scalar() or 0
            except Exception:
                conteggi[nome] = 0  # tabella non leggibile per qualche motivo: trattata come vuota, non un errore fatale
    return conteggi


def _nome_periodo(chiave_anno_mese: str) -> str:
    anno, mese = chiave_anno_mese.split("-")
    return f"{MESI_IT[int(mese) - 1].capitalize()} {anno}"


def _a_data(valore: Any) -> date | None:
    """La query "leggera" (sa_table/sa_column, senza informazioni di tipo —
    vedi sopra) non fa più convertire automaticamente a SQLAlchemy un
    valore data: per SQL Server/pyodbc arriva comunque un datetime nativo
    (conversione fatta dal driver, non da SQLAlchemy), ma per SQLite una
    colonna DATE è memorizzata come TEXT e torna una stringa grezza
    ("2026-01-15") — trovato provando su dati reali (Sampeyre, SQLite):
    senza questo parsing esplicito, ogni riga veniva scartata in
    silenzio e la tabella sembrava non avere nessun andamento."""
    if hasattr(valore, "date"):
        return valore.date()
    if isinstance(valore, date):
        return valore
    if isinstance(valore, str):
        try:
            return date.fromisoformat(valore[:10])
        except ValueError:
            return None
    return None


def _andamento_tabella(engine: Any, nome_tabella: str, col_data: str, col_numero: str) -> list[dict[str, Any]] | None:
    # sa_table()/sa_column() "leggeri" invece di db_engine.get_reflected_table:
    # non introspettano il database (nessuna chiamata di rete), servono solo
    # a generare SQL portabile (LIMIT, ORDER BY, quoting) per queste due
    # colonne che già conosciamo dai passaggi precedenti — evita la
    # reflection piena, misurata fino a 16 secondi su una tabella larga
    # reale, qui inaccettabile perché ripetuta per ogni tabella candidata.
    tabella = sa_table(nome_tabella, sa_column(col_data), sa_column(col_numero))
    query = (
        select(tabella.c[col_data], tabella.c[col_numero])
        .where(tabella.c[col_data].isnot(None))
        .order_by(tabella.c[col_data].desc())
        .limit(_LIMITE_RIGHE_PER_TABELLA)
    )
    oggi = date.today()
    per_mese: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    conteggio: dict[str, int] = defaultdict(int)
    with engine.connect() as conn:
        for valore_data, valore_numero in conn.execute(query):
            if valore_data is None or valore_numero is None:
                continue
            d = _a_data(valore_data)
            if d is None:
                continue
            if d > oggi:
                # Una data "di business" nel futuro è quasi sempre un valore
                # sentinella (es. "31/12/2070" per una scadenza/durata senza
                # fine, non una vera data ricorrente) — trovato provando su
                # dati reali (CS.DataInizioAmmortamento), dove dominava la
                # finestra "ultimi mesi" al posto delle date vere.
                continue
            chiave = f"{d.year:04d}-{d.month:02d}"
            per_mese[chiave] += Decimal(str(valore_numero))
            conteggio[chiave] += 1

    if len(per_mese) < 2:
        return None  # un solo mese di dati non è un andamento da mostrare
    if not any(v != 0 for v in per_mese.values()):
        return None  # colonna trovata per nome/tipo ma sempre a zero nei dati reali: niente da mostrare

    mesi_ordinati = sorted(per_mese)[-_MESI_MOSTRATI:]
    return [
        {"periodo": _nome_periodo(m), "totale": float(per_mese[m]), "movimenti": conteggio[m]}
        for m in mesi_ordinati
    ]


def _analizza(connection_string: str) -> list[dict[str, Any]]:
    engine = db_engine.get_engine(connection_string)
    nomi = db_engine.list_table_names(engine)

    conteggi = _conta_righe(engine, nomi)
    candidate = sorted(
        (n for n, c in conteggi.items() if c >= _SOGLIA_RIGHE_MINIMA),
        key=lambda n: -conteggi[n],
    )

    insp = inspect(engine)
    risultati: list[dict[str, Any]] = []
    for nome in candidate:
        if len(risultati) >= _LIMITE_TABELLE_MOSTRATE:
            break
        try:
            colonne = insp.get_columns(nome)
            pk = set((insp.get_pk_constraint(nome) or {}).get("constrained_columns") or [])
        except Exception:
            continue

        col_data = _colonna_data(colonne)
        col_numero = _colonna_numerica(colonne, pk)
        if not col_data or not col_numero:
            continue  # questa tabella non ha un verso "andamento nel tempo" da mostrare

        try:
            andamento = _andamento_tabella(engine, nome, col_data, col_numero)
        except Exception:
            continue
        if not andamento:
            continue

        risultati.append(
            {
                "tabella": nome,
                "colonna_data": col_data,
                "colonna_numero": col_numero,
                "righe_totali": conteggi[nome],
                "andamento": andamento,
            }
        )
    return risultati


def e_tipo_testuale(tipo_sql: str) -> bool:
    """Wrapper pubblico: né data né numero — usato da
    services.vista_automatica per scegliere una colonna "titolo" plausibile
    (qualunque colonna testuale va bene, non serve un tipo specifico)."""
    return not _e_tipo_data(tipo_sql) and not _e_tipo_numerico(tipo_sql)


def colonna_data_plausibile(colonne: list[dict]) -> str | None:
    """Wrapper pubblico di _colonna_data — stessa euristica usata per
    Andamenti, riusata da services.vista_automatica e
    services.segnalazione_automatica per decidere da sole la modalità di
    una Vista o la colonna di una Segnalazione creata dalla chat."""
    return _colonna_data(colonne)


def colonna_numerica_plausibile(colonne: list[dict], colonne_pk: set[str]) -> str | None:
    """Wrapper pubblico di _colonna_numerica: stessa euristica delle colonne
    "candidate" usata per Andamenti, riusata da services.esplorazione per
    l'esplorazione libera dalla chat — evita di duplicare la logica o di
    accedere a un dettaglio interno (_colonna_numerica) da un altro modulo."""
    return _colonna_numerica(colonne, colonne_pk)


def analizza_integrazione(connection_string: str) -> list[dict[str, Any]]:
    """Punto d'ingresso pubblico, cacheato (30 minuti): la scansione vera
    (`_analizza`) costa qualche secondo su un database con centinaia di
    tabelle, non va rifatta ad ogni apertura della pagina."""
    with _lock:
        voce = _cache.get(connection_string)
        if voce is not None and time.time() - voce[1] < _TTL_SECONDI:
            return voce[0]

    risultato = _analizza(connection_string)
    with _lock:
        _cache[connection_string] = (risultato, time.time())
    return risultato
