"""
Profilo contabile per database Arca (gestionale ERP di terze parti): stesse
funzioni di app.services.accounting_engine (bilancio, IVA, ammortamenti...)
ma lette dallo schema Arca invece che dal template "nonprofit_accounting" di
Sampeyre — sono due domini diversi, non generalizzabili in un motore unico
(uno schema ha "movimenti"/"categorie", l'altro "CGMovT"/"CGConto"/1521 righe
di struttura bilancio), ma stesso principio del db_templates.py già in uso:
un "profilo" per famiglia di schema, riusabile da OGNI database di quella
famiglia — collegare un secondo database Arca funziona subito, senza
configurazione, perché lo schema è standard tra installazioni Arca diverse.

A differenza di Sampeyre, qui non si CALCOLA quasi nulla: Arca ha già la
propria contabilità completa (bilancio civilistico, liquidazioni IVA,
ammortamenti cespiti) salvata nelle sue tabelle — il lavoro di questo modulo
è leggerla e presentarla in modo leggibile, non rifarla.
"""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Table, func, select

from app.services import db_engine
from app.services.accounting_engine import MESI_IT  # stessa tupla, non duplicata: vedi llm_client.py

# Tabelle la cui sola presenza segnala "questo è un database Arca" — usate per
# smistare automaticamente tra questo profilo e quello di Sampeyre (vedi
# api/accounting.py), senza chiedere all'utente di sapere cos'è il proprio schema.
_TABELLE_SEGNALE = {"CGMovT", "CGConto", "CGBil", "CGBilSaldoConto"}


def _engine(connection_string: str):
    # Engine + reflection cacheati (vedi app.services.db_engine): su Arca,
    # riflettere una tabella larga come CGMovR (108 colonne) da zero misura
    # 16 secondi — inaccettabile da rifare ad ogni richiesta, com'era prima.
    return db_engine.get_engine(connection_string)


def _reflect(engine: Any, table_name: str) -> Table:
    return db_engine.get_reflected_table(engine, table_name)


def _fetch_all(engine: Any, table: Table, **filtri: Any) -> list[dict[str, Any]]:
    query = select(table)
    for colonna, valore in filtri.items():
        query = query.where(table.c[colonna] == valore)
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query)]


def _pulito(valore: Any) -> str:
    """Molte colonne codice di Arca sono CHAR a lunghezza fissa, quindi
    arrivano riempite di spazi (es. 'A.A                 ') — inutilizzabili
    come chiave finché non vengono ripulite."""
    return (valore or "").strip()


def _codice_bil(valore: Any) -> str:
    """Come _pulito, ma anche case-insensitive: nei dati reali un conto può
    essere mappato a un codice voce con maiuscole diverse da come la voce è
    scritta in CGBil (es. 'E.A.5.B_90' contro 'E.A.5.b_90' nello stesso
    database) — un confronto sensibile al maiuscolo/minuscolo perderebbe
    silenziosamente quell'importo invece di segnalare un problema. Usata solo
    per i codici voce di bilancio, non per altri codici (causale, periodo)
    dove il maiuscolo/minuscolo non è mai stato un problema osservato."""
    return _pulito(valore).upper()


def _decimal(valore: Any) -> Decimal:
    if valore is None:
        return Decimal("0")
    return valore if isinstance(valore, Decimal) else Decimal(str(valore))


def is_arca_schema(connection_string: str) -> bool:
    """Rilevamento automatico: se il database ha queste tabelle, è (con
    altissima probabilità) uno schema Arca — permette a api/accounting.py di
    scegliere il profilo giusto senza che l'utente debba dichiararlo."""
    engine = _engine(connection_string)
    tabelle = set(db_engine.list_table_names(engine))
    return _TABELLE_SEGNALE.issubset(tabelle)


def list_periodi_bilancio(connection_string: str) -> list[dict[str, Any]]:
    """Esercizi per cui Arca ha già un bilancio chiuso/calcolato."""
    engine = _engine(connection_string)
    tabella = _reflect(engine, "CGBilPeriodo")
    periodi = _fetch_all(engine, tabella)
    return sorted(
        (
            {
                "codice": _pulito(p["Cd_CGBilPeriodo"]),
                "descrizione": p["Descrizione"],
                "data_inizio": str(p["DataInizio"])[:10],
                "data_fine": str(p["DataFine"])[:10],
            }
            for p in periodi
        ),
        key=lambda p: p["codice"],
    )


def _costruisci_albero(righe_struttura: list[dict], saldi_per_voce: dict[str, Decimal], sezione: str) -> list[dict]:
    """Ricompone la gerarchia del bilancio (Cd_Padre -> figli) e somma dal
    basso verso l'alto: una voce di livello superiore vale quanto la somma
    delle sue sotto-voci più un eventuale importo assegnato direttamente a
    lei (le foglie non hanno figli, solo l'importo diretto)."""
    voci = {
        _codice_bil(r["Cd_CGBil"]): r
        for r in righe_struttura
        if r["Sezione"].strip() == sezione
    }
    figli: dict[str, list[str]] = defaultdict(list)
    for codice, voce in voci.items():
        padre = _codice_bil(voce["Cd_Padre"])
        if padre:
            figli[padre].append(codice)

    cache: dict[str, Decimal] = {}

    def importo_di(codice: str) -> Decimal:
        if codice in cache:
            return cache[codice]
        totale = saldi_per_voce.get(codice, Decimal("0"))
        for figlio in figli.get(codice, []):
            totale += importo_di(figlio)
        cache[codice] = totale
        return totale

    radici = sorted(
        (codice for codice, voce in voci.items() if not _codice_bil(voce["Cd_Padre"])),
        key=lambda c: voci[c]["Ordine"],
    )

    def nodo(codice: str) -> dict:
        voce = voci[codice]
        sotto_voci = sorted(figli.get(codice, []), key=lambda c: voci[c]["Ordine"])
        return {
            "codice": codice,
            "descrizione": voce["Descrizione"].strip(),
            "livello": voce["Livello"],
            "importo": float(importo_di(codice)),
            "figli": [nodo(c) for c in sotto_voci],
        }

    return [nodo(c) for c in radici]


def _causali_chiusura_apertura(engine: Any) -> set[str]:
    """Codici causale con Tipo 'F' (bilancio di chiusura) o 'E' (bilancio di
    apertura) — flag di sistema di Arca, non configurazione azienda-
    specifica (verificato: sono le uniche causali con questi due Tipo).
    Le scritture di chiusura azzerano i conti economici a fine esercizio
    portando il saldo allo Stato Patrimoniale: sommarle nel Conto Economico
    annullerebbe esattamente i movimenti reali dell'anno."""
    causali = _fetch_all(engine, _reflect(engine, "CGCausale"))
    return {_pulito(c["Cd_CGCausale"]) for c in causali if c["Tipo"] in ("E", "F")}


def _mappa_conto_bilancio(engine: Any, id_tassonomia: int) -> dict[str, str]:
    """{codice conto: codice voce di bilancio}, dalla mappatura corrente
    (CGBilConto) — non da 'Old_Cd_CGBil1'/'Old_Cd_CGBil2' su CGConto, che
    nonostante il nome generico è la mappatura deprecata: la presenza del
    prefisso "Old_" si scopre solo leggendo lo schema con attenzione."""
    righe = _fetch_all(engine, _reflect(engine, "CGBilConto"), Id_CGBilTassonomia=id_tassonomia)
    return {_pulito(r["Cd_CGConto"]): _codice_bil(r["Cd_CGBil1"]) for r in righe if r["Cd_CGBil1"]}


def _saldi_per_voce_bilancio(
    engine: Any, movr: Table, mappa_conto_bil: dict[str, str], filtro_where: Any = None
) -> dict[str, Decimal]:
    """Somma Dare/Avere di ogni movimento (CGMovR, il dettaglio riga — non
    CGMovT, che è solo la testata) raggruppato per voce di bilancio a cui il
    conto movimentato appartiene. Segno finale = Avere - Dare: un saldo
    naturalmente "Avere" (ricavi, debiti, patrimonio netto) esce positivo,
    uno naturalmente "Dare" (costi) esce negativo — sommati tornano al
    risultato d'esercizio con il segno giusto, verificato contro
    CGBilPeriodo.UtilePerdita.

    `movr` va passata già riflessa dal chiamante (non ri-riflessa qui): due
    reflection separate della stessa tabella creano due oggetti Table Python
    distinti, e usarli insieme in una query genera un prodotto cartesiano
    invece di un filtro — scoperto proprio così, con un errore SQL a runtime."""
    query = select(movr.c.Cd_CGConto, movr.c.DareAvere, movr.c.ImportoE)
    if filtro_where is not None:
        query = query.where(filtro_where)
    saldi: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    with engine.connect() as conn:
        for cd_conto, dare_avere, importo in conn.execute(query):
            voce = mappa_conto_bil.get(_pulito(cd_conto))
            if voce is None:
                continue  # conto non mappato su questa tassonomia (es. conti d'ordine)
            segno = -1 if dare_avere == "D" else 1
            saldi[voce] += segno * _decimal(importo)
    return saldi


def compute_bilancio(connection_string: str, cd_periodo: str | None = None) -> dict[str, Any]:
    """Bilancio civilistico (art. 2425/2424 c.c.), ricostruito dai movimenti
    veri (CGMovR) mappati alle voci ufficiali che Arca già definisce
    (CGBilConto + CGBil) — non dallo snapshot CGBilSaldoConto, che in
    pratica risulta popolato solo parzialmente (verificato: 20 conti su 904
    per un intero esercizio in un caso reale) e userebbe numeri incompleti.

    Conto Economico: solo i movimenti dell'esercizio richiesto, escluse le
    scritture di apertura/chiusura (altrimenti si annullerebbero a vicenda
    con i movimenti reali). Stato Patrimoniale: cumulato su tutta la storia
    fino alla fine del periodo, incluse apertura/chiusura (i saldi
    patrimoniali si accumulano nel tempo, non si azzerano ogni anno).

    Se l'esercizio richiesto è un anno per cui Arca non ha ancora generato
    un periodo di bilancio ufficiale (tipico per l'anno in corso, prima
    della chiusura di fine anno — un'azienda che opera dal vivo scrive
    movimenti tutto l'anno molto prima di "chiudere" il bilancio), ne viene
    costruito uno provvisorio al volo: stessa tassonomia (struttura voci)
    dell'ultimo periodo ufficiale disponibile, applicata ai movimenti reali
    già registrati per quell'anno. Segnalato esplicitamente come
    provvisorio — non è un bilancio che Arca ha validato, solo una lettura
    onesta di ciò che c'è scritto finora."""
    engine = _engine(connection_string)
    periodi = _fetch_all(engine, _reflect(engine, "CGBilPeriodo"))
    if not periodi:
        raise ValueError("Nessun periodo di bilancio trovato in questo database Arca")

    periodo = None
    provvisorio = False
    if cd_periodo:
        periodo = next((p for p in periodi if _pulito(p["Cd_CGBilPeriodo"]) == cd_periodo), None)
    if periodo is None and cd_periodo and cd_periodo.strip().isdigit():
        riferimento = max(periodi, key=lambda p: p["DataFine"])
        anno = int(cd_periodo)
        fine_anno = datetime(anno, 12, 31)
        periodo = {
            "Cd_CGBilPeriodo": cd_periodo,
            "Id_CGBilTassonomia": riferimento["Id_CGBilTassonomia"],
            "DataFine": min(fine_anno, datetime.now()) if anno == date.today().year else fine_anno,
            "UtilePerdita": None,
        }
        provvisorio = True
    if periodo is None:
        if cd_periodo:
            raise ValueError(f"Periodo di bilancio '{cd_periodo}' non trovato")
        periodo = max(periodi, key=lambda p: p["DataFine"])

    righe_struttura = _fetch_all(
        engine, _reflect(engine, "CGBil"), Id_CGBilTassonomia=periodo["Id_CGBilTassonomia"]
    )
    mappa_conto_bil = _mappa_conto_bilancio(engine, periodo["Id_CGBilTassonomia"])
    causali_apertura_chiusura = _causali_chiusura_apertura(engine)

    movr = _reflect(engine, "CGMovR")
    saldi_economico = _saldi_per_voce_bilancio(
        engine,
        movr,
        mappa_conto_bil,
        (movr.c.Cd_CGEsercizio_R == periodo["Cd_CGBilPeriodo"])
        & (movr.c.Cd_CGCausale.notin_(causali_apertura_chiusura)),
    )
    saldi_patrimoniale = _saldi_per_voce_bilancio(
        engine, movr, mappa_conto_bil, movr.c.DtReg <= periodo["DataFine"]
    )

    conto_economico = _costruisci_albero(righe_struttura, saldi_economico, "E")
    risultato_ricalcolato = round(sum(v["importo"] for v in conto_economico), 2)
    risultato_ufficiale = None if periodo["UtilePerdita"] is None else float(_decimal(periodo["UtilePerdita"]))
    # Trasparenza invece di fidarsi ciecamente: se il ricalcolo dai movimenti
    # veri non coincide con quanto Arca ha registrato come risultato
    # ufficiale (capitato per il primo anno di un database reale, ~528€ su
    # un totale di ~9.000 — verosimilmente una rettifica manuale d'epoca mai
    # transitata come scrittura contabile), lo si segnala esplicitamente
    # invece di mostrare un numero solo e nascondere la discrepanza. Per un
    # periodo provvisorio non esiste un "ufficiale" con cui confrontare.
    scarto = None if risultato_ufficiale is None else round(risultato_ricalcolato - risultato_ufficiale, 2)

    nota = (
        "Bilancio ricostruito dai movimenti contabili reali (non da uno snapshot "
        "precalcolato, spesso incompleto) — il risultato ricalcolato è confrontato "
        "con quello ufficiale registrato in Arca; se non coincidono esattamente "
        "significa che in Arca esiste una rettifica non tracciabile dai movimenti "
        "(tipico del primo anno di digitalizzazione di una contabilità)."
    )
    if provvisorio:
        nota = (
            f"Arca non ha ancora un bilancio ufficiale per il {_pulito(periodo['Cd_CGBilPeriodo'])} "
            "(tipico per l'esercizio in corso, prima della chiusura) — questo è ricostruito al volo "
            "dai movimenti reali registrati finora, con la struttura dell'ultimo bilancio ufficiale "
            "disponibile. Non è un bilancio validato da Arca."
        )

    return {
        "profilo": "arca",
        "periodo": _pulito(periodo["Cd_CGBilPeriodo"]),
        "provvisorio": provvisorio,
        "risultato_esercizio": risultato_ufficiale,
        "risultato_ricalcolato": risultato_ricalcolato,
        "scarto_da_verificare": scarto if scarto is not None and abs(scarto) >= 0.01 else None,
        "stato_patrimoniale_attivo": _costruisci_albero(righe_struttura, saldi_patrimoniale, "A"),
        "stato_patrimoniale_passivo": _costruisci_albero(righe_struttura, saldi_patrimoniale, "P"),
        "conto_economico": conto_economico,
        "nota": nota,
    }


def compute_iva(connection_string: str, anno: int) -> dict[str, Any]:
    """Liquidazioni IVA per l'anno richiesto, lette direttamente da Arca
    (CGLiqIva) — a differenza del bilancio, qui non c'è nulla da ricostruire:
    la liquidazione periodica è un dato che l'azienda ha già calcolato (e
    tipicamente già presentato) per gli adempimenti fiscali, riportato così
    come Arca lo ha salvato, senza reinterpretare i segni."""
    engine = _engine(connection_string)
    righe = _fetch_all(engine, _reflect(engine, "CGLiqIva"), Anno=anno)
    periodi = [
        {
            # Periodo 0 in questo database è il riepilogo annuale, 1-4 i
            # trimestri — ma non è detto sia universale: mostrato così
            # com'è, senza etichette (mensile/trimestrale) inventate.
            "periodo": r["Periodo"],
            "iva_esigibile": float(_decimal(r["Iva_Esigibile"])),
            "iva_detratta": float(_decimal(r["Iva_Detratta"])),
            "saldo_periodo": float(_decimal(r["Iva_Credito_Debito"])),
            "iva_dovuta": float(_decimal(r["Iva_Dovuta"])),
            "versato": float(_decimal(r["Vers_Importo"])),
            "definitiva": bool(r["Definitiva"]),
        }
        for r in sorted(righe, key=lambda r: r["Periodo"])
    ]
    # Nessun errore se non ci sono ancora liquidazioni per l'anno richiesto
    # (tipico per l'esercizio in corso, prima della prima liquidazione
    # periodica): una lista vuota è un dato onesto, non un problema — a
    # differenza del bilancio non c'è nulla da ricostruire al volo qui,
    # le liquidazioni sono un adempimento che l'azienda fa quando arriva
    # la scadenza, non qualcosa che Cortex può anticipare.
    return {
        "profilo": "arca",
        "anno": anno,
        "periodi": periodi,
        "nota": "Liquidazioni IVA lette direttamente da Arca (CGLiqIva) — non ricalcolate da Cortex.",
    }


def compute_ammortamenti(connection_string: str, anno: int) -> dict[str, Any]:
    """Cespiti e relativa quota di ammortamento per l'anno richiesto, letti
    da CS (anagrafica cespite, con costo storico e fondo cumulato) — stesso
    principio di app.accounting_engine.compute_ammortamenti per Sampeyre
    (quota = costo × percentuale configurata), usato qui perché in questo
    database i movimenti di dettaglio (CSMov/CSMovimento, che registrerebbero
    la quota effettivamente contabilizzata anno per anno) sono vuoti — la
    quota è quindi una stima dalla percentuale configurata, non un valore
    letto da una scrittura contabile reale. Il fondo e il valore netto invece
    SONO dati reali (S_Amm_Civ), cumulati ad oggi — non specifici dell'anno."""
    engine = _engine(connection_string)
    fine_anno = date(anno, 12, 31)
    cespiti = _fetch_all(engine, _reflect(engine, "CS"))
    risultato = []
    for c in cespiti:
        inizio = c["DataInizioAmmortamento"]
        if inizio is None or inizio.date() > fine_anno:
            continue  # non ancora in ammortamento in quell'anno
        costo = _decimal(c["S_Acquisizione"])
        fondo = _decimal(c["S_Amm_Civ"])
        percentuale = _decimal(c["Perc_Civ"])
        risultato.append(
            {
                "codice": _pulito(c["Cd_CS"]),
                "descrizione": (c["Descrizione"] or "").strip(),
                "valore_acquisto": float(costo),
                "percentuale_ammortamento": float(percentuale),
                "quota_annua_stimata": float((costo * percentuale / 100).quantize(Decimal("0.01"))),
                "fondo_ammortamento_attuale": float(fondo),
                "valore_netto_attuale": float(costo - fondo),
                "dismesso": bool(c["S_Ven_Def"]),
            }
        )
    risultato.sort(key=lambda r: r["codice"])
    return {
        "profilo": "arca",
        "anno": anno,
        "cespiti": risultato,
        "totale_quota_annua_stimata": round(sum(r["quota_annua_stimata"] for r in risultato), 2),
        "totale_valore_netto_attuale": round(sum(r["valore_netto_attuale"] for r in risultato), 2),
        "nota": (
            "La quota annua è stimata dalla percentuale di ammortamento configurata sul "
            "cespite (costo × percentuale): i movimenti di ammortamento dettagliati non "
            "sono popolati in questo database, quindi non è una quota letta da una "
            "scrittura contabile reale come per il resto di questo modulo. Fondo e valore "
            "netto sono invece dati reali, cumulati ad oggi."
        ),
    }


def compute_saldi(connection_string: str) -> dict[str, float]:
    """Saldo attuale di ogni conto di liquidità (banche + cassa contanti) —
    equivalente Arca di app.accounting_engine.compute_saldi per Sampeyre,
    ma qui i conti non sono un elenco fisso ("Banca"/"Cassa"/"Titoli"): sono
    quelli che l'azienda stessa ha marcato come conto di liquidità in Arca
    (`CGConto.ContoBanca`), che tipicamente include sia i conti correnti
    bancari veri sia la cassa contanti nello stesso flag. Somma di tutti i
    movimenti reali (CGMovR) mai registrati su quel conto, stesso principio
    "Dare - Avere" già usato per lo Stato Patrimoniale del bilancio."""
    engine = _engine(connection_string)
    conti = _fetch_all(engine, _reflect(engine, "CGConto"), ContoBanca=True)
    if not conti:
        return {}

    movr = _reflect(engine, "CGMovR")
    codici_conto = {_pulito(c["Cd_CGConto"]): (c["Descrizione"] or "").strip() for c in conti}
    saldi: dict[str, Decimal] = {descrizione: Decimal("0") for descrizione in codici_conto.values()}

    query = select(movr.c.Cd_CGConto, movr.c.DareAvere, movr.c.ImportoE).where(
        movr.c.Cd_CGConto.in_(codici_conto.keys())
    )
    with engine.connect() as conn:
        for cd_conto, dare_avere, importo in conn.execute(query):
            descrizione = codici_conto[_pulito(cd_conto)]
            segno = 1 if dare_avere == "D" else -1
            saldi[descrizione] += segno * _decimal(importo)

    return {descrizione: float(saldo) for descrizione, saldo in saldi.items()}


# --- Funzioni per i comandi chat (grafici/tabelle a domanda) ---------------
#
# Equivalenti Arca di accounting_engine.compute_spese_per_categoria /
# list_movimenti / compute_andamento_mensile, usate da agent_brain.py per
# rispondere a richieste come "mostrami le spese di luglio" anche quando
# l'integrazione collegata è un database Arca invece del template Sampeyre.
#
# Arca non ha una tabella "categorie" configurata dall'azienda: la
# "categoria" più vicina che offre già è la voce di Conto Economico (CGBil,
# Sezione 'E') a cui il conto movimentato è mappato tramite CGBilConto —
# la stessa classificazione già usata e verificata per il bilancio (stessa
# tassonomia, stessa esclusione delle scritture di apertura/chiusura, stesso
# segno Avere-Dare: netto positivo = ricavo/entrata, netto negativo =
# costo/uscita). Un conto che non mappa a nessuna voce di Sezione 'E'
# (patrimoniale, o non mappato affatto) non ha un "verso" entrata/uscita e
# viene escluso dai grafici — non è un dato mancante, è semplicemente un
# movimento patrimoniale (es. un pagamento fornitore), non un costo/ricavo
# del periodo.


def _tassonomia_corrente(engine: Any) -> int:
    """Tassonomia (struttura voci) dell'ultimo periodo di bilancio disponibile
    — stessa scelta di default già usata da compute_bilancio quando non viene
    richiesto un periodo specifico."""
    periodi = _fetch_all(engine, _reflect(engine, "CGBilPeriodo"))
    if not periodi:
        raise ValueError("Nessun periodo di bilancio trovato in questo database Arca")
    return max(periodi, key=lambda p: p["DataFine"])["Id_CGBilTassonomia"]


def _voci_economico(engine: Any, id_tassonomia: int) -> dict[str, str]:
    """{codice voce: descrizione}, solo per le voci di Conto Economico
    (Sezione 'E') — le uniche che hanno senso come "categoria" di
    entrata/uscita in un grafico."""
    righe = _fetch_all(engine, _reflect(engine, "CGBil"), Id_CGBilTassonomia=id_tassonomia)
    return {_codice_bil(r["Cd_CGBil"]): r["Descrizione"].strip() for r in righe if r["Sezione"].strip() == "E"}


def _intervallo_mese(anno: int, mese: int) -> tuple[date, date]:
    """[inizio, fine) del mese richiesto — fine esclusiva, per evitare il
    solito problema del "31 vs 30 vs 28/29 giorni" confrontando solo il primo
    del mese successivo."""
    inizio = date(anno, mese, 1)
    fine = date(anno + 1, 1, 1) if mese == 12 else date(anno, mese + 1, 1)
    return inizio, fine


def compute_spese_per_categoria(
    connection_string: str, anno: int, mese: int, tipo: str = "uscita"
) -> list[dict[str, Any]]:
    """Totale movimenti del mese raggruppati per voce di Conto Economico,
    filtrati per verso (entrata|uscita) — equivalente Arca di
    accounting_engine.compute_spese_per_categoria."""
    engine = _engine(connection_string)
    id_tassonomia = _tassonomia_corrente(engine)
    mappa_conto_bil = _mappa_conto_bilancio(engine, id_tassonomia)
    descrizioni_voce = _voci_economico(engine, id_tassonomia)
    causali_apertura_chiusura = _causali_chiusura_apertura(engine)

    movr = _reflect(engine, "CGMovR")
    inizio, fine = _intervallo_mese(anno, mese)
    saldi = _saldi_per_voce_bilancio(
        engine,
        movr,
        mappa_conto_bil,
        (movr.c.DtReg >= inizio)
        & (movr.c.DtReg < fine)
        & (movr.c.Cd_CGCausale.notin_(causali_apertura_chiusura)),
    )

    risultati = []
    for codice, totale in saldi.items():
        descrizione = descrizioni_voce.get(codice)
        if descrizione is None or totale == 0:
            continue  # non una voce di Conto Economico (patrimoniale) o nessun movimento netto nel mese
        e_entrata = totale > 0
        if (tipo == "entrata") != e_entrata:
            continue
        risultati.append({"categoria_codice": codice, "nome": descrizione, "totale": float(abs(totale))})

    risultati.sort(key=lambda r: r["totale"], reverse=True)
    return risultati


def list_movimenti(connection_string: str, anno: int, mese: int, tipo: str | None = None) -> list[dict[str, Any]]:
    """Righe grezze di CGMovR del mese richiesto (non aggregate), con conto e
    documento di testata (CGMovT) risolti in descrizione leggibile —
    equivalente Arca di accounting_engine.list_movimenti. `tipo` opzionale
    (entrata|uscita) filtra sulla stessa classificazione di
    compute_spese_per_categoria; senza `tipo` mostra tutti i movimenti del
    mese, incluse le voci patrimoniali (che senza un verso richiesto non
    hanno motivo di essere escluse)."""
    engine = _engine(connection_string)
    id_tassonomia = _tassonomia_corrente(engine)
    mappa_conto_bil = _mappa_conto_bilancio(engine, id_tassonomia)
    descrizioni_voce = _voci_economico(engine, id_tassonomia)
    causali_apertura_chiusura = _causali_chiusura_apertura(engine)

    nome_conto = {
        _pulito(c["Cd_CGConto"]): (c["Descrizione"] or "").strip()
        for c in _fetch_all(engine, _reflect(engine, "CGConto"))
    }
    descr_testata = {
        r["Id_CGMovT"]: (r["Descrizione"] or "").strip() for r in _fetch_all(engine, _reflect(engine, "CGMovT"))
    }

    movr = _reflect(engine, "CGMovR")
    inizio, fine = _intervallo_mese(anno, mese)
    query = select(
        movr.c.DtReg, movr.c.Cd_CGConto, movr.c.DareAvere, movr.c.ImportoE, movr.c.Id_CGMovT
    ).where(
        (movr.c.DtReg >= inizio)
        & (movr.c.DtReg < fine)
        & (movr.c.Cd_CGCausale.notin_(causali_apertura_chiusura))
    )

    righe = []
    with engine.connect() as conn:
        for dtreg, cd_conto, dare_avere, importo, id_movt in conn.execute(query):
            codice_conto = _pulito(cd_conto)
            voce = mappa_conto_bil.get(codice_conto)
            descrizione_voce = descrizioni_voce.get(voce) if voce else None
            segno = -1 if dare_avere == "D" else 1  # stesso segno del Conto Economico del bilancio
            if tipo is not None:
                if descrizione_voce is None:
                    continue  # movimento patrimoniale: nessun verso entrata/uscita da confrontare col filtro
                if (tipo == "entrata") != (segno > 0):
                    continue
            data = dtreg.date() if hasattr(dtreg, "date") else dtreg
            righe.append(
                {
                    "data": data.isoformat(),
                    "descrizione": descr_testata.get(id_movt) or nome_conto.get(codice_conto, codice_conto),
                    "categoria": descrizione_voce or "Patrimoniale",
                    "conto": nome_conto.get(codice_conto, codice_conto),
                    "importo": float(segno * _decimal(importo)),
                }
            )
    righe.sort(key=lambda r: r["data"])
    return righe


def compute_andamento_mensile(connection_string: str, anno: int, tipo: str = "uscita") -> list[dict[str, Any]]:
    """Totale per ciascuno dei 12 mesi dell'anno, stesso verso
    (entrata|uscita) di compute_spese_per_categoria — equivalente Arca di
    accounting_engine.compute_andamento_mensile."""
    engine = _engine(connection_string)
    id_tassonomia = _tassonomia_corrente(engine)
    mappa_conto_bil = _mappa_conto_bilancio(engine, id_tassonomia)
    descrizioni_voce = _voci_economico(engine, id_tassonomia)
    causali_apertura_chiusura = _causali_chiusura_apertura(engine)

    movr = _reflect(engine, "CGMovR")
    query = select(movr.c.DtReg, movr.c.Cd_CGConto, movr.c.DareAvere, movr.c.ImportoE).where(
        (movr.c.DtReg >= date(anno, 1, 1))
        & (movr.c.DtReg < date(anno + 1, 1, 1))
        & (movr.c.Cd_CGCausale.notin_(causali_apertura_chiusura))
    )
    per_mese: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    with engine.connect() as conn:
        for dtreg, cd_conto, dare_avere, importo in conn.execute(query):
            voce = mappa_conto_bil.get(_pulito(cd_conto))
            if voce is None or voce not in descrizioni_voce:
                continue
            segno = -1 if dare_avere == "D" else 1
            if (tipo == "entrata") != (segno > 0):
                continue
            mese = dtreg.month if hasattr(dtreg, "month") else dtreg.date().month
            per_mese[mese] += segno * _decimal(importo)

    return [
        {"mese": m, "nome_mese": MESI_IT[m - 1], "totale": float(abs(per_mese.get(m, Decimal("0"))))}
        for m in range(1, 13)
    ]


# --- Modelli pronti (Viste pre-costruite) -----------------------------------
#
# Punto 3 del feedback dell'utente: configurare una Vista scegliendo a mano
# tabella e colonne tra le 380 di un database Arca è troppo difficile
# rispetto a farlo su Sampeyre (5 tabelle, nomi leggibili). Per i casi d'uso
# più comuni (chi mi deve pagare, chi devo pagare) non serve farlo scegliere
# all'utente: Cortex conosce già lo schema Arca standard (stesso principio
# già usato per bilancio/IVA/saldi), quindi può costruire la vista da solo —
# l'utente vede subito un risultato, non un configuratore.


def _saldi_anagrafiche(connection_string: str, tipo: str) -> list[dict[str, Any]]:
    """Saldo aperto per ciascun cliente o fornitore (tipo: 'cliente' o
    'fornitore'), sommando Dare-Avere di tutti i movimenti mai registrati su
    quel nominativo (CGMovR.Cd_CF, la "partita" cliente/fornitore) — stessa
    convenzione Attivo/Passivo già usata per lo Stato Patrimoniale del
    bilancio e per compute_saldi: un saldo positivo è un credito verso quel
    nominativo (per un cliente, ti deve soldi; per un fornitore, è un caso
    raro ma possibile — un acconto versato non ancora fatturato)."""
    engine = _engine(connection_string)
    campo = "Cliente" if tipo == "cliente" else "Fornitore"
    anagrafiche = _fetch_all(engine, _reflect(engine, "CF"), **{campo: True})
    if not anagrafiche:
        return []
    nomi = {_pulito(a["Cd_CF"]): (a["Descrizione"] or "").strip() for a in anagrafiche}

    movr = _reflect(engine, "CGMovR")
    query = select(movr.c.Cd_CF, movr.c.DareAvere, movr.c.ImportoE).where(movr.c.Cd_CF.in_(nomi.keys()))
    saldi: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    with engine.connect() as conn:
        for cd_cf, dare_avere, importo in conn.execute(query):
            segno = 1 if dare_avere == "D" else -1
            saldi[_pulito(cd_cf)] += segno * _decimal(importo)

    return [
        {"codice": codice, "nome": nomi[codice], "saldo": float(saldo)}
        for codice, saldo in saldi.items()
        if abs(saldo) >= 0.01  # conto pareggiato: nulla da mostrare, non un valore mancante
    ]


def compute_clienti_scoperti(connection_string: str) -> dict[str, Any]:
    """Clienti con un saldo ancora a debito verso l'azienda — il modello
    pronto "chi mi deve ancora pagare"."""
    righe = sorted(
        (r for r in _saldi_anagrafiche(connection_string, "cliente") if r["saldo"] > 0),
        key=lambda r: r["saldo"],
        reverse=True,
    )
    return {
        "profilo": "arca",
        "righe": righe,
        "totale": round(sum(r["saldo"] for r in righe), 2),
        "nota": (
            "Saldo aperto per cliente (Dare - Avere di tutti i movimenti mai registrati sulla sua "
            "partita) — solo i clienti con un saldo ancora a debito verso l'azienda sono mostrati."
        ),
    }


def compute_fornitori_da_pagare(connection_string: str) -> dict[str, Any]:
    """Fornitori verso cui l'azienda ha ancora un debito aperto — il modello
    pronto "chi devo ancora pagare"."""
    righe = sorted(
        (
            {"codice": r["codice"], "nome": r["nome"], "saldo": round(-r["saldo"], 2)}
            for r in _saldi_anagrafiche(connection_string, "fornitore")
            if r["saldo"] < 0
        ),
        key=lambda r: r["saldo"],
        reverse=True,
    )
    return {
        "profilo": "arca",
        "righe": righe,
        "totale": round(sum(r["saldo"] for r in righe), 2),
        "nota": (
            "Saldo da pagare per fornitore (Avere - Dare di tutti i movimenti mai registrati sulla "
            "sua partita) — solo i fornitori verso cui l'azienda ha ancora un debito aperto sono "
            "mostrati."
        ),
    }


def ultimo_periodo_con_movimenti(connection_string: str) -> tuple[int, int] | None:
    """Anno e mese dell'ultimo movimento registrato (MAX(DtReg) su CGMovR,
    non l'intera tabella caricata in memoria: su un database Arca reale
    CGMovR può avere centinaia di migliaia di righe) — usato dalla Dashboard
    per "cosa è cambiato" a partire dall'ultima attività contabile reale
    invece che dal mese di calendario corrente: un database la cui ultima
    registrazione non è recente (tipico per un database dimostrativo, o
    un'azienda in ritardo con le registrazioni) altrimenti confronterebbe
    sempre due mesi vuoti. None se non c'è nessun movimento registrato."""
    engine = _engine(connection_string)
    movr = _reflect(engine, "CGMovR")
    with engine.connect() as conn:
        ultima_data = conn.execute(select(func.max(movr.c.DtReg))).scalar()
    if ultima_data is None:
        return None
    d = ultima_data.date() if hasattr(ultima_data, "date") else ultima_data
    return (d.year, d.month)
