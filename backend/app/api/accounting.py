"""
Motore contabile (Fase C): saldi, ammortamenti, IVA, budget, anomalie e
bilancio calcolati sul database collegato di un tenant.

Due profili possibili, smistati automaticamente in base allo schema rilevato
(vedi _profilo): il template "nonprofit_accounting" di Sampeyre (tabelle
categorie/movimenti/cespiti/soglie_budget, tutto calcolato da Cortex), oppure
uno schema Arca (app.services.accounting_engine_arca — tabelle
CGMovT/CGConto/CGBil, dati letti/ricostruiti da un gestionale che li ha già).
Sono due domini distinti con forme di risposta diverse: il frontend
distingue in base al campo "profilo" nella risposta, non serve che l'utente
dichiari quale sta usando. Un'integrazione che non è né l'uno né l'altro
riceve un errore chiaro invece di un risultato silenziosamente sbagliato.
"""
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import Response

from app.api.auth import get_current_user
from app.api.deps import get_connection_string, require_admin
from app.models.user import User
from app.services import accounting_engine, accounting_engine_arca, bank_reconciliation, export_engine, narrazione, previsione

router = APIRouter(prefix="/integrations/{integration_id}/accounting", tags=["accounting"])


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # tabella mancante, colonna inattesa, connessione non valida...
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Impossibile calcolare: questa integrazione ha lo schema atteso? ({exc})",
        ) from exc


def _e_arca(connection_string: str) -> bool:
    try:
        return accounting_engine_arca.is_arca_schema(connection_string)
    except Exception:
        return False  # connessione non raggiungibile ora: lascia decidere al ramo Sampeyre, che darà l'errore vero


@router.get("/profilo")
def get_profilo(connection_string: str = Depends(get_connection_string)) -> dict:
    """Quale dei due profili contabili usare per questa integrazione — il
    frontend lo chiama per primo per sapere quali altre chiamate ha senso
    fare (saldi/budget/anomalie esistono solo per Sampeyre, ammortamenti
    dal profilo Arca ha una forma diversa da quello Sampeyre, ecc.), invece
    di scoprirlo da un errore generico."""
    return {"profilo": "arca" if _e_arca(connection_string) else "sampeyre"}


@router.get("/saldi")
def get_saldi(connection_string: str = Depends(get_connection_string)) -> dict[str, float]:
    if _e_arca(connection_string):
        return _run(accounting_engine_arca.compute_saldi, connection_string)
    return _run(accounting_engine.compute_saldi, connection_string)


def _tabella_anagrafiche(dati: dict, titolo: str) -> dict:
    """Forma già pronta per WidgetCanvas (stessa forma di "table" usata da
    Viste/visualize_tool) — i "modelli pronti" sotto restituiscono
    direttamente questo invece dei dati grezzi: l'utente deve vedere subito
    un risultato, non passare da un configuratore per un caso già noto."""
    return {
        "type": "table",
        "title": titolo,
        "columns": [
            {"key": "nome", "label": "Nominativo"},
            {"key": "codice", "label": "Codice"},
            {"key": "saldo", "label": "Saldo"},
        ],
        "rows": dati["righe"],
        "primary_key": None,
        "actions": [],
        "totale": dati["totale"],
        "nota": dati["nota"],
    }


@router.get("/modelli/clienti-scoperti")
def get_clienti_scoperti(connection_string: str = Depends(get_connection_string)) -> dict:
    """Modello pronto (solo profilo Arca): clienti con un saldo ancora a
    debito verso l'azienda — nessuna configurazione richiesta, vedi punto 3
    del feedback dell'utente in PLAN.md (Viste troppo difficili su Arca)."""
    if not _e_arca(connection_string):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Questo modello è disponibile solo per database Arca (usa una Vista normale per altri database).",
        )
    dati = _run(accounting_engine_arca.compute_clienti_scoperti, connection_string)
    return _tabella_anagrafiche(dati, "Clienti con saldo scoperto")


@router.get("/modelli/fornitori-da-pagare")
def get_fornitori_da_pagare(connection_string: str = Depends(get_connection_string)) -> dict:
    """Modello pronto (solo profilo Arca): fornitori verso cui l'azienda ha
    ancora un debito aperto."""
    if not _e_arca(connection_string):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Questo modello è disponibile solo per database Arca (usa una Vista normale per altri database).",
        )
    dati = _run(accounting_engine_arca.compute_fornitori_da_pagare, connection_string)
    return _tabella_anagrafiche(dati, "Fornitori da pagare")


@router.get("/spiegazione")
def get_spiegazione(
    anno: int | None = None,
    mese: int | None = None,
    tipo: str = "uscita",
    connection_string: str = Depends(get_connection_string),
) -> dict:
    """Spiegazione automatica dello scostamento rispetto al mese precedente
    — non solo il totale, quale voce ha inciso di più (vedi
    services/narrazione.py). Generico per entrambi i profili: entrambi i
    motori espongono la stessa compute_spese_per_categoria."""
    oggi = date.today()
    anno = anno or oggi.year
    mese = mese or oggi.month
    motore = accounting_engine_arca if _e_arca(connection_string) else accounting_engine
    return _run(narrazione.spiega_scostamento, motore, connection_string, anno, mese, tipo)


@router.get("/previsione-cassa")
def get_previsione_cassa(connection_string: str = Depends(get_connection_string)) -> dict:
    """Proiezione della liquidità per i prossimi mesi dal flusso di cassa
    reale — non solo lo stato attuale (vedi services/previsione.py).
    Generico per entrambi i profili."""
    motore = accounting_engine_arca if _e_arca(connection_string) else accounting_engine
    return _run(previsione.previsione_liquidita, motore, connection_string)


@router.get("/periodi-bilancio")
def get_periodi_bilancio(connection_string: str = Depends(get_connection_string)) -> dict:
    """Solo per il profilo Arca: elenco degli esercizi per cui esiste già un
    bilancio (per popolare una selezione invece di un anno libero — Sampeyre
    non ha un equivalente, qualunque anno con movimenti va bene)."""
    if not _e_arca(connection_string):
        return {"periodi": []}
    return {"periodi": _run(accounting_engine_arca.list_periodi_bilancio, connection_string)}


@router.get("/ammortamenti")
def get_ammortamenti(
    anno: int | None = None, connection_string: str = Depends(get_connection_string)
) -> dict:
    # Default a None invece di date.today().year: valutato in fase di definizione
    # della funzione (una volta sola, all'avvio), congelerebbe l'anno al giorno in
    # cui il server è partito invece che a "oggi" ad ogni richiesta.
    anno = anno or date.today().year
    if _e_arca(connection_string):
        return _run(accounting_engine_arca.compute_ammortamenti, connection_string, anno)
    risultati = _run(accounting_engine.compute_ammortamenti, connection_string, anno)
    totale = sum(r["quota_annuale"] for r in risultati)
    return {"profilo": "sampeyre", "anno": anno, "cespiti": risultati, "totale": round(totale, 2)}


@router.get("/iva")
def get_iva(anno: int | None = None, connection_string: str = Depends(get_connection_string)) -> dict:
    anno = anno or date.today().year
    if _e_arca(connection_string):
        return _run(accounting_engine_arca.compute_iva, connection_string, anno)
    return {"profilo": "sampeyre", **_run(accounting_engine.compute_iva, connection_string, anno)}


@router.get("/budget")
def get_budget(
    anno: int | None = None,
    mese: int | None = None,
    connection_string: str = Depends(get_connection_string),
) -> dict:
    oggi = date.today()
    anno = anno or oggi.year
    mese = mese or oggi.month
    risultati = _run(accounting_engine.check_budget, connection_string, anno, mese)
    return {"anno": anno, "mese": mese, "categorie": risultati}


@router.get("/anomalie")
def get_anomalie(connection_string: str = Depends(get_connection_string)) -> dict:
    return {"anomalie": _run(accounting_engine.detect_anomalie, connection_string)}


@router.get("/bilancio")
def get_bilancio(
    anno: int | None = None, periodo: str | None = None, connection_string: str = Depends(get_connection_string)
) -> dict:
    if _e_arca(connection_string):
        # Arca identifica gli esercizi con un codice (spesso ma non sempre un
        # anno) invece che un intero — vedi /periodi-bilancio per l'elenco.
        return _run(accounting_engine_arca.compute_bilancio, connection_string, periodo or (str(anno) if anno else None))
    anno = anno or date.today().year
    return {"profilo": "sampeyre", **_run(accounting_engine.compute_bilancio, connection_string, anno)}


@router.get("/bilancio/export.pdf")
def export_bilancio_pdf(
    anno: int | None = None,
    connection_string: str = Depends(get_connection_string),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Il bilancio come documento PDF stampabile — la compensazione esplicita
    per aver perso il "programma desktop con dati in locale" del piano
    originale (PLAN.md, Sezione 2): il dato deve poter uscire da Cortex.
    Solo per il profilo Sampeyre per ora: il bilancio Arca ha una struttura
    gerarchica diversa (voci annidate, non un raggruppamento piatto) che
    merita un layout PDF proprio, non ancora costruito."""
    if _e_arca(connection_string):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Export PDF non ancora disponibile per il bilancio Arca (struttura gerarchica, layout diverso).",
        )
    anno = anno or date.today().year
    bilancio = _run(accounting_engine.compute_bilancio, connection_string, anno)
    contenuto = export_engine.bilancio_a_pdf(bilancio, current_user.company_name or "")
    nome_file = quote(f"Bilancio {anno}.pdf")
    return Response(
        content=contenuto,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{nome_file}"},
    )


@router.post("/riconciliazione")
async def riconcilia(
    estratto_conto: UploadFile,
    tolleranza_giorni: int = 3,
    connection_string: str = Depends(get_connection_string),
    _admin: User = Depends(require_admin),
) -> dict:
    """Carica un estratto conto (CSV con colonne data/importo/descrizione) e lo
    abbina ai Movimenti su conto Banca non ancora riconciliati. I movimenti
    abbinati vengono marcati come riconciliati; ritorna anche cosa non ha
    trovato corrispondenza da nessuna delle due parti."""
    contenuto_grezzo = await estratto_conto.read()
    try:
        contenuto = contenuto_grezzo.decode("utf-8-sig")  # utf-8-sig: tollera il BOM di Excel
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"File non leggibile come CSV: {exc}") from exc

    try:
        righe = bank_reconciliation.parse_estratto_conto_csv(contenuto)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"CSV non valido: {exc}") from exc

    if not righe:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Il CSV non contiene righe da riconciliare.")

    return _run(bank_reconciliation.reconcile, connection_string, righe, tolleranza_giorni)
