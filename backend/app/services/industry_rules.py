"""
Regole per adattare la UI e la logica in base al settore (industry) dell'azienda.
Ogni settore ha statistiche dashboard, widget, voci di menu e strumenti (tools)
preferiti diversi. Le voci di menu (`nav_items`) sono lette dal frontend invece di
essere hardcodate nella Sidebar: aggiungere pagine specifiche di un settore (es. la
Prima Nota per la finanza no-profit) significa estendere questa configurazione,
senza toccare il componente React.

Le icone sono nomi di componenti di `lucide-react` (vedi Sidebar.jsx).
"""
from typing import Any

# Voci di menu comuni a tutti i settori: oggi esistono solo queste due pagine.
# Un settore può aggiungerne altre (vedi "nonprofit_finance" quando i moduli
# Prima Nota/Cespiti/Bilancio saranno implementati) senza cambiare il frontend.
_BASE_NAV_ITEMS: list[dict[str, str]] = [
    {"to": "/dashboard", "label": "Dashboard", "icon": "LayoutDashboard"},
    # Riepilogo di tutte le aziende a cui l'utente ha accesso (vedi
    # api/auth.py, Membership) — non specifica di un settore, chi ha un solo
    # cliente la vede comunque (utile per aggiungerne altri via invito).
    {"to": "/portfolio", "label": "I miei clienti", "icon": "Building"},
    {"to": "/integrations", "label": "Integrazioni", "icon": "Plug"},
    # Esploratore dati generico (vedi api/data_explorer.py): stessa pagina per
    # qualunque settore, non solo per la finanza no-profit.
    {"to": "/data", "label": "Dati", "icon": "Database"},
    # Grafici che Cortex trova e disegna da solo analizzando le tabelle
    # collegate, senza Viste o Segnalazioni da configurare (vedi
    # services/analisi_automatica.py, api/integrations.py) — funziona su
    # qualunque database, non solo su uno schema contabile riconosciuto.
    {"to": "/andamenti", "label": "Andamenti", "icon": "TrendingUp"},
    # Amministratori dell'azienda + codice invito (vedi api/team.py): generico,
    # nessun limite al numero di amministratori per nessun settore.
    {"to": "/team", "label": "Team", "icon": "Users"},
    # Viste configurabili su qualunque tabella collegata (vedi api/views.py):
    # generico per qualunque settore, non solo la finanza no-profit.
    {"to": "/viste", "label": "Viste", "icon": "LayoutTemplate"},
    # Segnalazioni proattive (vedi api/alerts.py, services/alert_engine.py):
    # regole che l'agente valuta da solo sui dati collegati, generico come le
    # Viste — non specifiche di un settore.
    {"to": "/segnalazioni", "label": "Segnalazioni", "icon": "BellRing"},
    # Contabilità (vedi api/accounting.py): non più specifica della finanza
    # no-profit da quando esiste il profilo Arca (services/accounting_engine_arca.py)
    # — la pagina smista da sola tra i profili in base allo schema
    # dell'integrazione scelta, un'azienda senza nessuno dei due schemi
    # riconosciuti vede solo "nessun database compatibile collegato".
    {"to": "/contabilita", "label": "Contabilità", "icon": "Calculator"},
]

INDUSTRY_RULES: dict[str, dict[str, Any]] = {
    "generic": {
        "label": "Generico",
        "icon": "LayoutGrid",
        "dashboard_widgets": ["overview", "recent_activity"],
        "preferred_tools": ["email_tool", "scraper_tool"],
        "nav_items": _BASE_NAV_ITEMS,
    },
    "ecommerce": {
        "label": "E-commerce",
        "icon": "ShoppingCart",
        "dashboard_widgets": ["sales", "orders", "inventory", "customers"],
        "preferred_tools": ["db_connector", "email_tool"],
        "nav_items": _BASE_NAV_ITEMS,
    },
    "real_estate": {
        "label": "Immobiliare",
        "icon": "Building2",
        "dashboard_widgets": ["listings", "leads", "appointments"],
        "preferred_tools": ["scraper_tool", "email_tool"],
        "nav_items": _BASE_NAV_ITEMS,
    },
    "professional_services": {
        "label": "Servizi Professionali",
        "icon": "Briefcase",
        "dashboard_widgets": ["clients", "invoices", "appointments"],
        "preferred_tools": ["email_tool", "db_connector"],
        "nav_items": _BASE_NAV_ITEMS,
    },
    "nonprofit_finance": {
        "label": "Finanza No-Profit",
        "icon": "Landmark",
        # Placeholder in attesa del motore contabile (Fase C del piano): saldi
        # cassa/banca, movimenti del mese, quote di ammortamento da registrare.
        "dashboard_widgets": ["saldo_cassa_banca", "movimenti_mese", "cespiti_da_ammortizzare"],
        "preferred_tools": ["db_connector", "email_tool"],
        "nav_items": _BASE_NAV_ITEMS,
    },
}


def get_rules_for_industry(industry: str) -> dict[str, Any]:
    """Ritorna la configurazione UI/tool per un dato settore, con fallback a 'generic'."""
    return INDUSTRY_RULES.get(industry, INDUSTRY_RULES["generic"])
