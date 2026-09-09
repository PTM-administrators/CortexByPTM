"""
Dati per la Dashboard React: configurazione UI in base al settore (industry)
dell'utente, più — quando l'azienda ha un database contabile collegato
riconosciuto (Sampeyre o Arca, rilevato da solo) — un riepilogo finanziario
reale al posto delle statistiche segnaposto.

Prima del 20 agosto 2026 "stats" era sempre {"overview": 0, "recent_activity": 0}
(o l'equivalente per gli altri settori) con un commento esplicito nel codice
("in produzione questi valori arriverebbero da servizi reali") mai risolto
dopo che il motore contabile (Fase C) e le spiegazioni automatiche sono
arrivati — la Dashboard, la prima pagina che si vede aprendo Cortex, restava
vuota anche per un'azienda con dati veri collegati. Il riepilogo qui sotto
riusa `compute_saldi` e `services/narrazione.spiega_scostamento`, già
verificati altrove: non è un calcolo nuovo, solo il primo posto dove questi
dati compaiono senza che l'utente debba chiedere nulla.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.security import decrypt_credentials
from app.database import get_db
from app.models.integrations import Integration
from app.models.membership import Membership
from app.models.organization import Organization
from app.models.user import User
from app.services import accounting_engine, accounting_engine_arca, alert_engine, narrazione, previsione
from app.services.industry_rules import get_rules_for_industry
from app.services.integration_providers import find_first_database_integration

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class NavItem(BaseModel):
    to: str
    label: str
    icon: str


class RiepilogoFinanziario(BaseModel):
    saldi: dict[str, float]
    totale_liquidita: float
    narrazione: str
    periodo: str
    # Solo quando la previsione di cassa (services/previsione.py) segnala che
    # la liquidità scenderebbe sotto zero proiettando il ritmo attuale —
    # None nel caso comune, per non riempire la Dashboard di un avviso
    # quando non c'è nulla da segnalare.
    avviso_cassa: str | None = None


class DashboardResponse(BaseModel):
    industry: str
    industry_label: str
    industry_icon: str
    widgets: list[str]
    stats: dict[str, int]
    nav_items: list[NavItem]
    # None per un'azienda senza database contabile riconosciuto collegato —
    # non un errore, solo "niente da riepilogare ancora" (vedi Integrazioni).
    riepilogo_finanziario: RiepilogoFinanziario | None = None
    # Zero qui distingue "azienda appena creata, non ha ancora collegato
    # nulla" (mostra un invito a iniziare) da "ha integrazioni ma nessuna
    # riconosciuta come contabile" (mostra le statistiche generiche per
    # settore) — due situazioni diverse che il frontend deve trattare
    # diversamente, vedi Dashboard.jsx.
    numero_integrazioni: int = 0


def _riepilogo_finanziario(db: Session, organization_id: int) -> RiepilogoFinanziario | None:
    integrazione = find_first_database_integration(db, organization_id)
    if integrazione is None:
        return None
    connection_string = decrypt_credentials(integrazione.credentials).get("connection_string")
    if not connection_string:
        return None

    try:
        e_arca = accounting_engine_arca.is_arca_schema(connection_string)
    except Exception:
        e_arca = False
    motore = accounting_engine_arca if e_arca else accounting_engine

    try:
        saldi = motore.compute_saldi(connection_string)
    except Exception:
        return None  # non uno schema contabile riconosciuto: niente da riepilogare qui

    try:
        # L'ultimo periodo con movimenti reali, non il mese di calendario
        # corrente: un'azienda la cui contabilità si ferma a un anno fa (o
        # un database dimostrativo) altrimenti confronterebbe sempre due
        # mesi vuoti — vedi narrazione.spiega_ultimo_periodo_con_dati.
        spiegazione = narrazione.spiega_ultimo_periodo_con_dati(motore, connection_string, "uscita")
        testo, periodo = spiegazione["narrazione"], spiegazione["periodo"]
    except Exception:
        # I saldi restano comunque utili anche se la spiegazione fallisce
        # (es. nessun movimento storico da confrontare) — non un tutto o niente.
        testo, periodo = "", ""

    try:
        avviso_cassa = previsione.previsione_liquidita(motore, connection_string)["avviso"]
    except Exception:
        avviso_cassa = None  # non bloccante, stesso principio della spiegazione sopra

    return RiepilogoFinanziario(
        saldi=saldi,
        totale_liquidita=round(sum(saldi.values()), 2),
        narrazione=testo,
        periodo=periodo,
        avviso_cassa=avviso_cassa,
    )


@router.get("", response_model=DashboardResponse)
def get_dashboard(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DashboardResponse:
    """Ritorna la configurazione UI (widget, menu, icone) per il settore
    dell'utente, più il riepilogo finanziario reale se disponibile. La
    Sidebar usa `nav_items`/`industry_icon` per adattarsi dinamicamente
    invece di avere un menu fisso."""
    rules = get_rules_for_industry(current_user.industry)
    stats = {widget: 0 for widget in rules["dashboard_widgets"]}
    numero_integrazioni = (
        db.query(Integration).filter(Integration.organization_id == current_user.organization_id).count()
    )

    return DashboardResponse(
        industry=current_user.industry,
        industry_label=rules["label"],
        industry_icon=rules["icon"],
        widgets=rules["dashboard_widgets"],
        stats=stats,
        nav_items=rules["nav_items"],
        riepilogo_finanziario=_riepilogo_finanziario(db, current_user.organization_id),
        numero_integrazioni=numero_integrazioni,
    )


class RiepilogoAzienda(BaseModel):
    """Una riga del Portfolio: un colpo d'occhio su un'azienda cliente senza
    dover cambiare azienda attiva per guardarla — per chi segue più aziende
    diverse (alcune con un gestionale vero, altre senza nulla) da un solo
    account, invece di un login separato per ognuna."""

    organization_id: int
    company_name: str
    industry_label: str
    riepilogo_finanziario: RiepilogoFinanziario | None = None
    segnalazioni_aperte: int
    e_azienda_attiva: bool


@router.get("/portfolio", response_model=list[RiepilogoAzienda])
def get_portfolio(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[RiepilogoAzienda]:
    """Riepilogo di TUTTE le aziende a cui l'utente ha accesso (vedi
    api/auth.py, Membership), non solo quella attiva — il Portfolio di chi
    ha più clienti diversi. Riusa esattamente la stessa logica della
    Dashboard singola (_riepilogo_finanziario) e delle Segnalazioni
    (alert_engine.valuta_tutte_le_regole), una volta per azienda: nessun
    calcolo nuovo, solo la stessa vista ripetuta su più aziende."""
    aziende = (
        db.query(Organization)
        .join(Membership, Membership.organization_id == Organization.id)
        .filter(Membership.user_id == current_user.id)
        .order_by(Organization.company_name)
        .all()
    )
    risultato = []
    for azienda in aziende:
        rules = get_rules_for_industry(azienda.industry)
        segnalazioni = alert_engine.valuta_tutte_le_regole(db, azienda.id)
        risultato.append(
            RiepilogoAzienda(
                organization_id=azienda.id,
                company_name=azienda.company_name,
                industry_label=rules["label"],
                riepilogo_finanziario=_riepilogo_finanziario(db, azienda.id),
                segnalazioni_aperte=len(segnalazioni),
                e_azienda_attiva=azienda.id == current_user.organization_id,
            )
        )
    return risultato
