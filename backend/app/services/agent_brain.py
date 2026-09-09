"""
L'agente operativo: riceve un messaggio, decide quale tool serve (tramite
LLMClient — vedi app.services.llm, oggi lo StubLLMClient gratuito) e lo
esegue davvero usando le credenziali salvate nell'Hub Integrazioni
dell'utente. A differenza delle Fasi A-C, qui l'agente non si limita più a
descrivere cosa farebbe: agisce.

Le azioni con effetti verso l'esterno (oggi: inviare un'email) non vengono
eseguite subito: l'agente prepara una bozza e la lascia come "azione
pendente" (app.services.agent_state), in attesa di conferma esplicita
dall'utente tramite POST /api/agent/confirm/{action_id}. Le azioni di sola
lettura (una ricerca online, un grafico) vengono invece eseguite subito.
"""
from datetime import date
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.security import decrypt_credentials
from app.models.integrations import Integration
from app.models.saved_view import SavedView
from app.models.user import User
from app.services import agent_handlers
from app.services import (
    accounting_engine,
    accounting_engine_arca,
    agent_state,
    alert_engine,
    conversation_state,
    data_source,
    db_engine,
    esplorazione,
    narrazione,
    previsione,
    segnalazione_automatica,
    view_rendering,
    vista_automatica,
)
from app.services.accounting_engine import MESI_IT
from app.services.integration_providers import find_first_database_integration
from app.services.llm import AgentDecision, LLMClient, StubLLMClient, get_llm_client
from app.tools import scraper_tool
from app.services.agent_widgets import (
    _chart_andamento,
    _chart_composizione,
    _chart_confronto,
    _chart_periodo,
    _nome_periodo,
    _widget_elenco,
    _widget_quadro_generale,
    _widget_saldo,
    _widget_spiegazione,
)

# Parole che segnalano "voglio vedere qualcosa" prima del nome di una vista
# salvata — senza una di queste, il nome della vista che compare per caso nel
# messaggio non basta a far scattare il richiamo (vedi _try_saved_view).
_TRIGGER_VISUALIZZAZIONE = ("mostrami", "fammi vedere", "apri", "vedi", "mostra", "dammi", "fai vedere")

# Parole che rendono plausibile che il messaggio riguardi il creare/vedere
# una Vista o una Segnalazione — usate SOLO per decidere se vale la pena
# pre-cercare una tabella e leggerne le colonne prima di chiedere a un LLM
# cosa fare (vedi _tabella_candidata): una domanda come "quanto abbiamo in
# banca?" non le contiene, e non paga quella query in più senza motivo.
_PAROLE_SCHEMA_UTILE = ("segnalazione", "segnalazioni", "vista", "viste", "avvisami", "avvertimi", "segnalami", "notificami")




class AgentBrain:
    """Cervello operativo dell'agente per un utente/richiesta specifici."""

    def __init__(self, db: Session, current_user: User, llm_client: LLMClient | None = None) -> None:
        self.db = db
        self.current_user = current_user
        self.llm_client = llm_client or get_llm_client()

    def _tabella_candidata(self, message: str) -> dict[str, Any] | None:
        """Pre-cerca (economica: solo corrispondenza sui NOMI di tabella,
        nessuna query dati — vedi esplorazione.trova_tabella_per_nome) una
        tabella pertinente al messaggio PRIMA ancora di chiedere a un LLM
        cosa fare, e ne legge le colonne reali — così un LLM vero può
        scegliere condition_type/colonna/modalità ragionando su nomi veri
        invece di doverli indovinare (vedi llm_client._istruzioni_sistema).
        Richiesta esplicita dell'utente (3 settembre 2026): "non deve usare
        template predefiniti ma la chat deve capire qualsiasi cosa voglia
        l'utente".

        Tentata solo se il messaggio somiglia a una richiesta di
        creare/vedere qualcosa (altrimenti ogni singolo messaggio, anche
        "ciao", pagherebbe una query in più senza motivo) — e qualunque
        fallimento (integrazione assente, connessione caduta, tabella non
        trovata) ritorna semplicemente None: l'LLM decide comunque, solo
        senza questo aiuto in più, esattamente come prima di questa
        modifica."""
        lowered = message.lower()
        if not any(p in lowered for p in _PAROLE_SCHEMA_UTILE):
            return None
        integration = agent_handlers._find_database_integration(self.db, self.current_user)
        if integration is None:
            return None
        try:
            connection_string = decrypt_credentials(integration.credentials).get("connection_string")
            if not connection_string:
                return None
            nome_tabella = esplorazione.trova_tabella_per_nome(connection_string, message)
            if not nome_tabella:
                return None
            engine = db_engine.get_engine(connection_string)
            colonne = inspect(engine).get_columns(nome_tabella)
            return {"nome": nome_tabella, "colonne": [c["name"] for c in colonne]}
        except Exception:
            return None  # un fallimento qui non deve rompere la decisione, solo privarla di questo aiuto

    def _contesto_decisione(self, message: str) -> dict[str, Any]:
        """Contesto passato a decide_action: settore dell'azienda, memoria
        conversazionale (vedi services/conversation_state — la cronologia
        come lista di dict, non le dataclass Turno direttamente, per non
        legare llm_client a un tipo interno di questo modulo) e, quando
        pertinente, la tabella candidata con le sue colonne reali. Senza
        storico/ultimo_contesto ogni messaggio veniva deciso da solo, senza
        nessuna nozione di cosa fosse stato chiesto prima (feedback
        dell'utente, 3 settembre 2026: "la chat è piuttosto inutile")."""
        return {
            "industry": self.current_user.industry,
            "storico": [
                {"ruolo": t.ruolo, "testo": t.testo}
                for t in conversation_state.storico(self.current_user.id)
            ],
            "ultimo_contesto_visualizzazione": conversation_state.ultimo_contesto_visualizzazione(
                self.current_user.id
            ),
            "tabella_candidata": self._tabella_candidata(message),
        }

    def _decidi_con_ripiego(self, message: str) -> AgentDecision:
        """Chiede al client configurato (StubLLMClient gratuito, oppure un
        LLM vero se una chiave è impostata — vedi llm_client.get_llm_client)
        — se quello vero fallisce (quota esaurita, rete, chiave non valida:
        capitato davvero con la quota giornaliera gratuita di Gemini, 20
        richieste/giorno per modello) degrada al riconoscimento a pattern
        invece di rompere la chat con un errore. Un provider a pagamento che
        smette di funzionare non deve rendere Cortex inutilizzabile — deve
        tornare silenziosamente al livello gratuito, sempre disponibile."""
        contesto = self._contesto_decisione(message)
        try:
            return self.llm_client.decide_action(message, context=contesto)
        except Exception:
            if isinstance(self.llm_client, StubLLMClient):
                raise  # già il ripiego: un errore qui è un bug vero, non va nascosto
            return StubLLMClient().decide_action(message, context=contesto)

    def handle_message(self, message: str) -> dict[str, Any]:
        risultato = self._decidi_e_esegui(message)
        # Registrato DOPO l'esecuzione (non prima) così la risposta
        # dell'agente entra nella cronologia insieme al messaggio che l'ha
        # generata — vedi services/conversation_state, usato dal prossimo
        # messaggio per un riferimento come "e il mese scorso?".
        conversation_state.aggiungi_turno(self.current_user.id, "utente", message)
        conversation_state.aggiungi_turno(self.current_user.id, "assistente", risultato.get("reply", ""))
        return risultato

    def _decidi_e_esegui(self, message: str) -> dict[str, Any]:
        # Controllato per primo, prima ancora dell'LLM/stub: se il messaggio
        # nomina una Vista già salvata (vedi Viste.jsx) con una parola che
        # segnala "voglio vederla", non serve indovinare nulla sullo schema —
        # il nome l'ha già scelto l'utente quando l'ha configurata.
        saved_view_result = self._try_saved_view(message)
        if saved_view_result is not None:
            return saved_view_result

        decision = self._decidi_con_ripiego(message)

        if decision.tool == "email_tool":
            return agent_handlers.handle_email(self.db, self.current_user, decision)
        if decision.tool == "scraper_tool":
            return agent_handlers.handle_search(decision)
        if decision.tool == "visualize_tool":
            return agent_handlers.handle_visualize(self.db, self.current_user, decision)
        if decision.tool == "esplora_tool":
            return agent_handlers.handle_esplora(self.db, self.current_user, decision, message)
        if decision.tool == "crea_vista_tool":
            return agent_handlers.handle_crea_vista(self.db, self.current_user, decision, message)
        if decision.tool == "crea_segnalazione_tool":
            return agent_handlers.handle_crea_segnalazione(self.db, self.current_user, decision, message)

        # "db_connector" e "none": nessuna azione da eseguire, solo la
        # risposta del LLM (es. un saluto).
        return {"action": decision.tool, "reply": decision.reply, "pending_action": None}

    def _try_saved_view(self, message: str) -> dict[str, Any] | None:
        """Riconosce un riferimento a una Vista salvata per nome (es.
        "mostrami gli annunci") e la mostra nella pagina principale. Nessun
        LLM: un confronto testuale col nome che l'utente stesso ha dato alla
        vista in fase di configurazione — non capisce richieste su tabelle
        mai configurate, quello resta il limite onesto di questa modalità
        gratuita."""
        lowered = message.lower()
        if not any(trigger in lowered for trigger in _TRIGGER_VISUALIZZAZIONE):
            return None

        views = (
            self.db.query(SavedView)
            .filter(SavedView.organization_id == self.current_user.organization_id)
            .all()
        )
        candidati = [v for v in views if v.name.lower() in lowered]
        if not candidati:
            return None
        vista = max(candidati, key=lambda v: len(v.name))  # nome più specifico tra quelli che combaciano

        integration = self.db.get(Integration, vista.integration_id)
        try:
            source = data_source.resolve(integration) if integration else None
        except ValueError:
            source = None
        if source is None:
            return {
                "action": "saved_view",
                "reply": f'Non trovo più la sorgente dati collegata alla vista "{vista.name}".',
                "pending_action": None,
            }

        try:
            widget = view_rendering.render_view_data(vista, source)
        except Exception as exc:
            return {
                "action": "saved_view",
                "reply": f'Non sono riuscito a mostrare "{vista.name}": {exc}',
                "pending_action": None,
            }

        return {"action": "saved_view", "reply": f'Ecco "{vista.name}".', "pending_action": None, "widget": widget}

