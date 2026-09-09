"""
L'agente operativo: riceve un messaggio, decide quale tool serve (tramite
LLMClient — vedi app.services.llm_client, oggi lo StubLLMClient gratuito) e lo
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
from app.services.llm_client import AgentDecision, LLMClient, StubLLMClient, get_llm_client
from app.tools import scraper_tool

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


def _find_integration(db: Session, user: User, providers: tuple[str, ...]) -> Integration | None:
    return (
        db.query(Integration)
        .filter(Integration.organization_id == user.organization_id, Integration.provider.in_(providers))
        .order_by(Integration.created_at)
        .first()
    )


def _motore_contabile(connection_string: str):
    """Sceglie fra i due motori (Sampeyre / Arca) con lo stesso rilevamento
    automatico già usato da api/accounting.py (_e_arca) — la chat deve capire
    da sola quale profilo ha davanti, l'utente non dichiara mai quale sta
    usando. Le due funzioni con lo stesso nome (compute_saldi,
    list_movimenti, compute_spese_per_categoria, compute_andamento_mensile)
    hanno la stessa forma di ritorno nei due motori, quindi il resto di
    _handle_visualize non deve sapere quale dei due sta chiamando."""
    try:
        if accounting_engine_arca.is_arca_schema(connection_string):
            return accounting_engine_arca
    except Exception:
        pass  # connessione non raggiungibile ora: lascia decidere al motore Sampeyre, che darà l'errore vero
    return accounting_engine


def _find_database_integration(db: Session, user: User) -> Integration | None:
    """Prima integrazione dell'azienda che espone un database (gestito o
    esterno) — stessa convenzione già usata da Contabilita.jsx per scegliere
    l'integrazione di default quando ce n'è più di una."""
    return find_first_database_integration(db, user.organization_id)


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
        integration = _find_database_integration(self.db, self.current_user)
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
            return self._handle_email(decision)
        if decision.tool == "scraper_tool":
            return self._handle_search(decision)
        if decision.tool == "visualize_tool":
            return self._handle_visualize(decision)
        if decision.tool == "esplora_tool":
            return self._handle_esplora(decision, message)
        if decision.tool == "crea_vista_tool":
            return self._handle_crea_vista(decision, message)
        if decision.tool == "crea_segnalazione_tool":
            return self._handle_crea_segnalazione(decision, message)

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

    def _handle_email(self, decision: AgentDecision) -> dict[str, Any]:
        if decision.missing_fields:
            return {"action": "email_tool", "reply": decision.reply, "pending_action": None}

        integration = _find_integration(self.db, self.current_user, ("gmail",))
        if integration is None:
            return {
                "action": "email_tool",
                "reply": (
                    "Non hai ancora collegato un'integrazione Gmail/SMTP: configurala nella "
                    "pagina Integrazioni, poi riprova."
                ),
                "pending_action": None,
            }

        action = agent_state.create_pending_action(self.current_user.id, "email_tool", decision.arguments)
        return {
            "action": "email_tool",
            "reply": decision.reply,
            "pending_action": {"id": action.id, "tool": "email_tool", "preview": decision.arguments},
        }

    def _handle_search(self, decision: AgentDecision) -> dict[str, Any]:
        query = decision.arguments.get("query", "")
        risultato = scraper_tool.web_search(query)
        if "error" in risultato:
            reply = f'{decision.reply} Non sono riuscito a completare la ricerca ({risultato["error"]}).'
        else:
            reply = f"{decision.reply} Ricerca eseguita (nessun riassunto automatico ancora — arriva nel prossimo passo della Fase D)."
        return {"action": "scraper_tool", "reply": reply, "pending_action": None}

    def _ricorda_contesto_visualizzazione(self, modo: str, tipo: str, anno: int, mese: int) -> None:
        """Salva l'ultima richiesta di visualizzazione risolta con successo
        (vedi services/conversation_state) — solo per i modi con un singolo
        periodo, gli unici per cui "il mese scorso" ha un significato
        univoco (StubLLMClient._decide_riferimento_relativo la legge al
        messaggio successivo)."""
        conversation_state.imposta_ultimo_contesto_visualizzazione(
            self.current_user.id, {"modo": modo, "tipo": tipo, "periodi": [[anno, mese]]}
        )

    def _handle_esplora(self, decision: AgentDecision, message: str) -> dict[str, Any]:
        """Esplorazione libera su qualunque tabella collegata (vedi
        services/esplorazione) — il "prossimo passo" a cui rimandava il
        vecchio ramo "db_connector": prima di questo l'agente non provava
        nemmeno a guardare i dati per una domanda fuori dai modi fissi di
        visualize_tool."""
        integration = _find_database_integration(self.db, self.current_user)
        if integration is None:
            return {
                "action": "esplora_tool",
                "reply": "Non hai ancora un database collegato: collegane uno nella pagina Integrazioni.",
                "pending_action": None,
            }
        connection_string = decrypt_credentials(integration.credentials).get("connection_string")
        if not connection_string:
            return {
                "action": "esplora_tool",
                "reply": "L'integrazione collegata non ha un database esplorabile.",
                "pending_action": None,
            }

        termine = decision.arguments.get("termine") or message
        try:
            trovato = esplorazione.cerca(connection_string, termine)
        except Exception as exc:  # tabella non leggibile, connessione caduta, ecc.
            return {
                "action": "esplora_tool",
                "reply": f"Non sono riuscito a cercare tra i dati collegati: {exc}",
                "pending_action": None,
            }

        if trovato is None:
            disponibili = esplorazione.tabelle_note(connection_string)
            if disponibili:
                elenco = ", ".join(r["tabella"] for r in disponibili[:8])
                reply = f'Non ho trovato dati su "{termine}". Le tabelle che riesco a leggere sono: {elenco}.'
            else:
                reply = f'Non ho trovato dati su "{termine}" in questo database.'
            return {"action": "esplora_tool", "reply": reply, "pending_action": None}

        if trovato["tipo"] == "andamento":
            widget = {
                "type": "line",
                "title": f"{trovato['tabella']} — andamento di {trovato['colonna_numero']}",
                "labels": [p["periodo"] for p in trovato["andamento"]],
                "series": [{"name": trovato["colonna_numero"], "data": [p["totale"] for p in trovato["andamento"]]}],
            }
            reply = f'Ecco l\'andamento di "{trovato["tabella"]}" — {trovato["righe_totali"]} righe totali.'
            return {"action": "esplora_tool", "reply": reply, "pending_action": None, "widget": widget}

        items = [{"label": "Righe totali", "value": trovato["righe"]}]
        if trovato.get("somma") is not None:
            items.append({"label": f"Totale {trovato['colonna_numero']}", "value": trovato["somma"], "format": "currency"})
        widget = {"type": "cards", "title": f'Tabella "{trovato["tabella"]}"', "items": items}
        return {
            "action": "esplora_tool",
            "reply": f'Ecco cosa ho trovato in "{trovato["tabella"]}".',
            "pending_action": None,
            "widget": widget,
        }

    def _handle_crea_vista(self, decision: AgentDecision, message: str) -> dict[str, Any]:
        """"mostrami i debitori" → trova la tabella, decide la modalità
        (da un LLM vero che ha visto le colonne reali, se ha scelto di
        passare 'mode'; altrimenti dall'euristica automatica), salva una
        Vista riusabile (vedi services/vista_automatica) invece di una
        risposta usa-e-getta — richiesta esplicita dell'utente (3 settembre
        2026): "l'utente vorrebbe vedere la tabella dei debitori e in
        automatico l'IA va a creare la vista perfetta e più opportuna"."""
        integration = _find_database_integration(self.db, self.current_user)
        if integration is None:
            return {
                "action": "crea_vista_tool",
                "reply": "Non hai ancora un database collegato: collegane uno nella pagina Integrazioni.",
                "pending_action": None,
            }
        connection_string = decrypt_credentials(integration.credentials).get("connection_string")
        if not connection_string:
            return {
                "action": "crea_vista_tool",
                "reply": "L'integrazione collegata non ha un database esplorabile.",
                "pending_action": None,
            }

        args = decision.arguments
        termine = args.get("termine") or message
        try:
            risultato = vista_automatica.crea_o_riusa_vista(
                self.db,
                integration,
                connection_string,
                termine,
                mode=args.get("mode"),
                colonna_data=args.get("colonna_data"),
                colonna_titolo=args.get("colonna_titolo"),
                colonna_sottotitolo=args.get("colonna_sottotitolo"),
                colonna_badge=args.get("colonna_badge"),
            )
        except Exception as exc:
            return {
                "action": "crea_vista_tool",
                "reply": f"Non sono riuscito a creare la vista: {exc}",
                "pending_action": None,
            }
        if risultato is None:
            return {
                "action": "crea_vista_tool",
                "reply": f'Non ho trovato una tabella che sembri corrispondere a "{termine}".',
                "pending_action": None,
            }

        vista, creata_ora, _nome_tabella = risultato
        try:
            source = data_source.resolve(integration)
            widget = view_rendering.render_view_data(vista, source)
        except Exception as exc:
            return {
                "action": "crea_vista_tool",
                "reply": f'Ho creato la vista "{vista.name}" ma non riesco a mostrarla: {exc}',
                "pending_action": None,
            }

        verbo = "Creata" if creata_ora else "Ecco"
        reply = (
            f'{verbo} la vista "{vista.name}" — la trovi anche nella pagina Viste, e la puoi ririchiamare '
            f'in qualunque momento scrivendo "mostrami {vista.name.lower()}".'
        )
        return {"action": "crea_vista_tool", "reply": reply, "pending_action": None, "widget": widget}

    def _handle_crea_segnalazione(self, decision: AgentDecision, message: str) -> dict[str, Any]:
        """"avvisami quando un debitore è scaduto", "crea una segnalazione
        per le spese maggiori di 1000 euro", o qualunque altra condizione
        che un LLM vero sappia esprimere avendo visto le colonne reali
        della tabella candidata (vedi services/segnalazione_automatica.py,
        _tabella_candidata) — trova tabella e colonna da sola, salva una
        Segnalazione vera, mostra subito quante righe scatterebbero oggi.
        Se non c'è un LLM vero (o non ha passato condition_type), ripiega
        sul riconoscimento a pattern di prima (scadenza/soglia)."""
        integration = _find_database_integration(self.db, self.current_user)
        if integration is None:
            return {
                "action": "crea_segnalazione_tool",
                "reply": "Non hai ancora un database collegato: collegane uno nella pagina Integrazioni.",
                "pending_action": None,
            }
        connection_string = decrypt_credentials(integration.credentials).get("connection_string")
        if not connection_string:
            return {
                "action": "crea_segnalazione_tool",
                "reply": "L'integrazione collegata non ha un database esplorabile.",
                "pending_action": None,
            }

        args = decision.arguments
        termine = args.get("termine") or message
        condition_type = args.get("condition_type")
        operatore = args.get("operatore")
        soglia = args.get("soglia")

        try:
            if condition_type:
                # Un LLM vero ha scelto lui stesso tipo/colonna, avendo
                # visto lo schema reale — nessun caso "1, 2 o 3" fissato in
                # anticipo da questo codice.
                risultato = segnalazione_automatica.crea_o_riusa_segnalazione(
                    self.db,
                    integration,
                    connection_string,
                    termine,
                    condition_type,
                    colonna=args.get("colonna"),
                    colonna_data=args.get("colonna_data"),
                    operatore=operatore,
                    soglia=float(soglia) if soglia is not None else None,
                    giorni_tolleranza=int(args.get("giorni_tolleranza") or 0),
                    colonna_gruppo=args.get("colonna_gruppo"),
                    soglia_deviazioni=float(args.get("soglia_deviazioni") or 2.0),
                )
            elif operatore is not None and soglia is not None:
                # Ripiego per StubLLMClient (nessun ragionamento, solo
                # un'espressione regolare — vedi llm_client._SOGLIA_RE).
                risultato = segnalazione_automatica.crea_o_riusa_segnalazione_soglia(
                    self.db, integration, connection_string, termine, operatore, float(soglia)
                )
            else:
                # Ripiego per StubLLMClient, caso scadenza.
                giorni_tolleranza = int(args.get("giorni_tolleranza") or 0)
                risultato = segnalazione_automatica.crea_o_riusa_segnalazione_scadenza(
                    self.db, integration, connection_string, termine, giorni_tolleranza
                )
        except Exception as exc:
            return {
                "action": "crea_segnalazione_tool",
                "reply": f"Non sono riuscito a creare la segnalazione: {exc}",
                "pending_action": None,
            }
        if risultato is None:
            return {
                "action": "crea_segnalazione_tool",
                "reply": (
                    f'Non ho trovato una tabella con una colonna adatta che corrisponda a "{termine}". '
                    "Puoi configurarla a mano nella pagina Segnalazioni."
                ),
                "pending_action": None,
            }

        regola, creata_ora, scattate = risultato
        verbo = "Creata" if creata_ora else "Trovata"
        parola_riga = "riga" if len(scattate) == 1 else "righe"
        reply = (
            f'{verbo} la segnalazione "{regola.name}" — con i criteri attuali oggi scatterebbe su '
            f"{len(scattate)} {parola_riga}. La trovi nella pagina Segnalazioni."
        )
        widget = {
            "type": "narrative",
            "title": regola.name,
            "text": "; ".join(s["dettaglio"] for s in scattate[:5]) or "Nessuna riga scattata al momento.",
        }
        return {"action": "crea_segnalazione_tool", "reply": reply, "pending_action": None, "widget": widget}

    def _handle_visualize(self, decision: AgentDecision) -> dict[str, Any]:
        integration = _find_database_integration(self.db, self.current_user)
        if integration is None:
            return {
                "action": "visualize_tool",
                "reply": "Non hai ancora un database collegato con dati finanziari: collegane uno nella pagina Integrazioni.",
                "pending_action": None,
            }

        connection_string = decrypt_credentials(integration.credentials).get("connection_string")
        if not connection_string:
            return {
                "action": "visualize_tool",
                "reply": "L'integrazione collegata non ha un database esplorabile.",
                "pending_action": None,
            }

        args = decision.arguments
        tipo = args.get("tipo", "uscita")
        modo = args.get("modo")
        motore = _motore_contabile(connection_string)

        try:
            if modo == "saldo":
                saldi = motore.compute_saldi(connection_string)
                widget = _widget_saldo(saldi)
            elif modo == "elenco":
                anno, mese = _periodo_richiesto(args)
                righe = motore.list_movimenti(connection_string, anno, mese, tipo)
                widget = _widget_elenco(righe, _nome_periodo(anno, mese))
                self._ricorda_contesto_visualizzazione("elenco", tipo, anno, mese)
            elif modo == "confronto":
                (anno1, mese1), (anno2, mese2) = args["periodi"]
                dati1 = motore.compute_spese_per_categoria(connection_string, anno1, mese1, tipo)
                dati2 = motore.compute_spese_per_categoria(connection_string, anno2, mese2, tipo)
                widget = _chart_confronto(dati1, dati2, _nome_periodo(anno1, mese1), _nome_periodo(anno2, mese2), tipo)
            elif modo == "periodo":
                anno, mese = _periodo_richiesto(args)
                dati = motore.compute_spese_per_categoria(connection_string, anno, mese, tipo)
                if args.get("composizione"):
                    widget = _chart_composizione(dati, _nome_periodo(anno, mese), tipo)
                else:
                    widget = _chart_periodo(dati, _nome_periodo(anno, mese), tipo)
                self._ricorda_contesto_visualizzazione("periodo", tipo, anno, mese)
            elif modo == "andamento":
                # "anno" non è obbligatorio nello schema (solo "modo" lo è):
                # un LLM vero può ometterlo se l'utente non ha specificato un
                # anno esplicito ("come sono andate le entrate ultimamente?")
                # — stesso ripiego di _periodo_richiesto, qui sul solo anno.
                anno = int(args["anno"]) if args.get("anno") else date.today().year
                dati = motore.compute_andamento_mensile(connection_string, anno, tipo)
                widget = _chart_andamento(dati, anno, tipo)
            elif modo == "spiegazione":
                anno, mese = _periodo_richiesto(args)
                risultato = narrazione.spiega_scostamento(motore, connection_string, anno, mese, tipo)
                widget = _widget_spiegazione(risultato)
                self._ricorda_contesto_visualizzazione("spiegazione", tipo, anno, mese)
            elif modo == "quadro_generale":
                saldi_qg = motore.compute_saldi(connection_string)
                spiegazione_qg = narrazione.spiega_ultimo_periodo_con_dati(motore, connection_string, "uscita")
                previsione_qg = previsione.previsione_liquidita(motore, connection_string)
                segnalazioni_qg = alert_engine.valuta_tutte_le_regole(self.db, self.current_user.organization_id)
                widget = _widget_quadro_generale(saldi_qg, spiegazione_qg, previsione_qg, segnalazioni_qg)
            else:
                return {"action": "visualize_tool", "reply": "Non ho capito cosa mostrare.", "pending_action": None}
        except Exception as exc:  # tabella mancante, schema inatteso, ecc.
            return {
                "action": "visualize_tool",
                "reply": f"Non sono riuscito a calcolare la vista: il database collegato ha lo schema atteso? ({exc})",
                "pending_action": None,
            }

        # "quadro_generale" non ha nessuna delle chiavi sotto (ha una sua
        # struttura composita) ma non è mai vuoto per costruzione — sarebbe
        # scartato per errore dal controllo che segue senza questa eccezione.
        vuoto = (
            widget.get("type") != "quadro_generale"
            and not widget.get("items")
            and not widget.get("rows")
            and not widget.get("labels")
            and not widget.get("text")
        )
        if vuoto:
            return {
                "action": "visualize_tool",
                "reply": f"{decision.reply} Non ho trovato movimenti per questo periodo.",
                "pending_action": None,
            }

        return {"action": "visualize_tool", "reply": decision.reply, "pending_action": None, "widget": widget}
