"""
Astrazione del client LLM usato dall'Agente Operativo (Fase D del piano):
un'interfaccia comune (`decide_action`) dietro cui può stare un client finto
(per sviluppare e testare senza spendere) o un provider reale, senza dover
toccare la logica dell'agente altrove — cambia solo `get_llm_client()`.

Decisione dell'11-12 agosto 2026: si costruisce tutta la Fase D fin da subito
con `StubLLMClient` (nessun costo), passando a `OpenAILLMClient` quando sarà
disponibile una chiave reale in `OPENAI_API_KEY` — un cambio di configurazione,
non di codice.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from app.core.config import settings
from app.services.accounting_engine import MESI_IT


@dataclass
class AgentDecision:
    """L'output strutturato che ci si aspetterebbe da un vero LLM con function
    calling: quale tool usare, con quali argomenti, quanto l'IA è sicura
    (soglia di fiducia, Sezione 7 del piano di progetto) e cosa manca per
    poter agire."""

    tool: str  # "email_tool" | "db_connector" | "scraper_tool" | "none"
    confidence: float  # 0..1
    arguments: dict[str, Any] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    reply: str = ""


class LLMClient(Protocol):
    def decide_action(self, message: str, context: dict[str, Any]) -> AgentDecision: ...


class StubLLMClient:
    """Client finto: stessa interfaccia di un vero LLM con function calling, ma
    la decisione è calcolata con regole locali invece che con una chiamata a
    pagamento. Pensato per sviluppare/testare l'esecuzione reale dei tool e il
    flusso di conferma (specialmente per l'invio email) a costo zero."""

    _EMAIL_RE = re.compile(r"[\w\.\-]+@[\w\.\-]+\.\w+")
    _EMAIL_WORDS = ("email", "mail", "manda", "invia", "scrivi a")
    _SEARCH_WORDS = ("cerca", "ricerca", "trova online", "search")
    _MESE_RE = re.compile(r"\b(" + "|".join(MESI_IT) + r")\b(?:\s+(\d{4}))?")
    _ANDAMENTO_WORDS = ("andamento", "trend", "durante l'anno", "nel corso dell'anno")
    _ENTRATE_WORDS = ("entrate", "ricavi", "incassi")
    _USCITE_WORDS = ("uscite", "spese", "costi")
    _SALDO_WORDS = ("saldo", "liquidità", "liquidita", "quanto abbiamo", "quanto c'è", "quanto ho")
    _ELENCO_WORDS = ("elenco", "lista", "elencami", "dammi i movimenti", "movimenti di")
    _COMPOSIZIONE_WORDS = ("composizione", "percentuale", "quota", "suddivisione", "ripartizione")
    _SPIEGAZIONE_WORDS = (
        "perché", "perche", "spiega", "spiegami", "cosa è cambiato", "cosa e cambiato",
        "come mai", "motivo dell'aumento", "motivo del calo",
    )
    _QUADRO_GENERALE_WORDS = (
        "quadro generale", "quadro completo", "riepilogo generale", "riepilogo completo",
        "panoramica", "come sta andando l'azienda", "come va l'azienda", "situazione generale",
        "situazione dell'azienda", "come stiamo andando",
    )
    # Un riferimento relativo ha senso solo se sappiamo già COSA si stava
    # guardando (vedi _decide_riferimento_relativo) — limite onesto di questa
    # modalità gratuita: capisce solo "il mese scorso/prima", non riferimenti
    # più liberi ("due mesi fa", "lo stesso periodo dell'anno scorso"), per
    # quelli serve un LLM vero con la cronologia (vedi GeminiLLMClient).
    _RELATIVI_PERIODO_PRECEDENTE = ("il mese scorso", "il mese prima", "mese precedente", "quello prima", "quello precedente")
    # Messaggi di cortesia che non vale la pena instradare verso una ricerca
    # nei dati collegati (vedi il fallback finale di decide_action) — senza
    # questo filtro, un semplice "grazie" produrrebbe una risposta strana tipo
    # "non ho trovato dati su 'grazie'".
    _SALUTI = ("ciao", "salve", "buongiorno", "buonasera", "buonanotte", "grazie", "ok", "va bene", "perfetto", "ottimo")
    # "mostrami/dammi X" senza un mese/andamento riconosciuto (altrimenti
    # avrebbe già vinto _decide_visualize) è un'intenzione di VEDERE una
    # tabella, non una domanda puntuale — vale la pena salvarla come Vista
    # riusabile invece di una risposta usa-e-getta (vedi crea_vista_tool).
    # Parole condivise con agent_brain._TRIGGER_VISUALIZZAZIONE: stesso
    # verbo, bersaglio diverso (una vista già salvata lì, una da creare qui).
    _CREA_VISTA_WORDS = (
        "mostrami", "fammi vedere", "vedi", "mostra", "dammi", "fai vedere",
        "crea una vista", "creami una vista", "salva una vista", "salvami una vista",
    )
    # Una Segnalazione automatica dalla chat è volutamente ristretta al caso
    # "scadenza superata" (vedi services/segnalazione_automatica.py): serve
    # SIA una parola di avviso SIA una di scadenza, non basta una sola —
    # "avvisami" da solo è troppo generico per sapere di cosa.
    _AVVISO_WORDS = ("avvisami", "avvertimi", "segnalami", "notificami")
    _SCADENZA_WORDS = ("scadut", "scaden", "ritardo")
    # Un secondo caso di Segnalazione automatica, oltre alla scadenza:
    # "crea una segnalazione per le spese maggiori di 1000 euro" — qui la
    # parola-chiave "segnalazione"/di avviso da sola non basta, serve anche
    # un confronto numerico riconoscibile (maggiore/minore di N), altrimenti
    # "le spese sono maggiori di 1000" verrebbe scambiato per una richiesta
    # di creazione. "i"/"a" opzionali dopo il verbo: "oltre i 1000", "sopra
    # a 1000" sono entrambe forme reali.
    _CREA_SEGNALAZIONE_WORDS = _AVVISO_WORDS + ("segnalazione", "segnalazioni", "avviso")
    _SOGLIA_RE = re.compile(
        r"(maggior[ei]|super(?:iore|iori)|sopra|oltre|minor[ei]|inferior[ei]|sotto)"
        r"\s+(?:d[ie]\s+|a\s+|i\s+)?(\d+(?:[.,]\d+)?)"
    )
    _OPERATORI_SOPRA = ("maggior", "super", "sopra", "oltre")

    def decide_action(self, message: str, context: dict[str, Any]) -> AgentDecision:
        lowered = message.lower()

        # Controllato per primo: una richiesta come "mandami un grafico delle
        # spese di luglio" conterrebbe "manda" (parola-chiave email) e finirebbe
        # nel ramo sbagliato se controllassi prima quello.
        visualize_decision = self._decide_visualize(lowered, context)
        if visualize_decision is not None:
            return visualize_decision

        if any(word in lowered for word in self._EMAIL_WORDS):
            return self._decide_email(message)
        if any(word in lowered for word in self._SEARCH_WORDS):
            return AgentDecision(
                tool="scraper_tool",
                confidence=0.8,
                arguments={"query": message},
                reply=f'Cerco online: "{message}".',
            )

        # "crea una segnalazione per le spese maggiori di 1000 euro" — il
        # secondo caso riconoscibile (soglia numerica): serve sia una parola
        # di segnalazione/avviso sia un confronto numerico esplicito,
        # altrimenti una frase come "le spese sono maggiori di 1000" verrebbe
        # scambiata per una richiesta di creazione (vedi _SOGLIA_RE sopra).
        match_soglia = self._SOGLIA_RE.search(lowered)
        if match_soglia and any(w in lowered for w in self._CREA_SEGNALAZIONE_WORDS):
            operatore = ">" if match_soglia.group(1).startswith(self._OPERATORI_SOPRA) else "<"
            soglia = float(match_soglia.group(2).replace(",", "."))
            return AgentDecision(
                tool="crea_segnalazione_tool",
                confidence=0.5,
                arguments={"termine": message, "operatore": operatore, "soglia": soglia},
                reply="Preparo la segnalazione...",
            )

        # "avvisami quando i debitori sono scaduti" — il caso scadenza, non
        # soglie/anomalie inventate a caso da un testo ambiguo (vedi
        # services/segnalazione_automatica.py).
        if any(w in lowered for w in self._AVVISO_WORDS) and any(w in lowered for w in self._SCADENZA_WORDS):
            return AgentDecision(
                tool="crea_segnalazione_tool",
                confidence=0.5,
                arguments={"termine": message},
                reply="Preparo la segnalazione...",
            )

        # "mostrami i debitori" — intenzione di vedere (e riusare) una
        # tabella, non solo una domanda puntuale: vale la pena salvarla come
        # Vista invece di una risposta usa-e-getta (vedi crea_vista_tool).
        if any(w in lowered for w in self._CREA_VISTA_WORDS):
            return AgentDecision(
                tool="crea_vista_tool",
                confidence=0.5,
                arguments={"termine": message},
                reply="Trovo la tabella giusta e preparo la vista...",
            )

        # Tutto il resto: prova a cercare tra i dati collegati (esplora_tool,
        # su QUALUNQUE tabella, non solo entrate/uscite) invece di rispondere
        # con un vicolo cieco fisso. Prima di questa modifica un messaggio
        # come "quanti fornitori abbiamo" cadeva qui con una risposta fissa
        # senza nemmeno aver provato a guardare i dati veri (feedback
        # dell'utente, 3 settembre 2026: "la chat è piuttosto inutile").
        pulito = lowered.strip(" !.?")
        ha_contenuto = any(len(w) >= 4 for w in re.findall(r"[a-zàèéìòù]+", lowered))
        if pulito in self._SALUTI or not ha_contenuto:
            return AgentDecision(tool="none", confidence=0.0, reply="Ciao! Dimmi cosa vuoi sapere sui tuoi dati.")
        return AgentDecision(
            tool="esplora_tool",
            confidence=0.35,
            arguments={"termine": message},
            reply="Cerco tra i dati collegati...",
        )

    def _decide_email(self, message: str) -> AgentDecision:
        destinatario = self._estrai_email(message)
        corpo = self._estrai_corpo(message)

        mancanti = []
        if not destinatario:
            mancanti.append("destinatario")
        if not corpo:
            mancanti.append("testo del messaggio")

        if mancanti:
            return AgentDecision(
                tool="email_tool",
                confidence=0.4,
                arguments={"to_address": destinatario, "subject": "Messaggio da Cortex", "body": corpo},
                missing_fields=mancanti,
                reply=f"Per preparare l'email mi manca: {', '.join(mancanti)}. Riprova specificandolo.",
            )

        return AgentDecision(
            tool="email_tool",
            confidence=0.9,
            arguments={"to_address": destinatario, "subject": "Messaggio da Cortex", "body": corpo},
            reply="Ho preparato la bozza dell'email qui sotto: controllala e conferma l'invio.",
        )

    def _decide_riferimento_relativo(self, lowered_message: str, context: dict[str, Any]) -> AgentDecision | None:
        """Un riferimento relativo ("e il mese scorso?") ha senso solo se
        sappiamo già COSA si stava guardando: eredita modo/tipo dall'ultima
        richiesta di visualizzazione risolta con successo in questa
        conversazione (vedi services/conversation_state, passato qui in
        context["ultimo_contesto_visualizzazione"] da AgentBrain), spostando
        solo il periodo indietro di un mese."""
        if not any(w in lowered_message for w in self._RELATIVI_PERIODO_PRECEDENTE):
            return None
        precedente = context.get("ultimo_contesto_visualizzazione")
        if not precedente or precedente.get("modo") not in ("periodo", "elenco", "spiegazione"):
            return None
        periodi = precedente.get("periodi")
        if not periodi:
            return None
        anno, mese = periodi[0]
        mese -= 1
        if mese == 0:
            mese, anno = 12, anno - 1
        nuovi_args = {**precedente, "periodi": [[anno, mese]]}
        parola_tipo = "entrate" if nuovi_args.get("tipo") == "entrata" else "spese"
        return AgentDecision(
            tool="visualize_tool",
            confidence=0.7,
            arguments=nuovi_args,
            reply=f"Ecco {'le ' + parola_tipo if precedente['modo'] != 'elenco' else 'i movimenti'} di {MESI_IT[mese - 1].capitalize()} {anno}.",
        )

    def _decide_visualize(self, lowered_message: str, context: dict[str, Any]) -> AgentDecision | None:
        """Riconosce richieste sui dati finanziari e le trasforma in una
        richiesta di visualizzazione strutturata (grafico, tabella o schede),
        mostrata nella pagina principale — non nella chat (vedi Dashboard.jsx).
        Riconoscimento a pattern (nomi mese + parole chiave), non vera
        comprensione del linguaggio: una frase troppo diversa da questi schemi
        non viene riconosciuta — vedi OpenAILLMClient per quando serve
        generalizzare davvero."""
        entrata_richiesta = any(w in lowered_message for w in self._ENTRATE_WORDS)
        uscita_richiesta = any(w in lowered_message for w in self._USCITE_WORDS)
        # Grafici/andamento hanno sempre bisogno di un tipo per essere un
        # confronto sensato: "spese" di default (il caso più comune). Un
        # "elenco" invece, se non specificato, mostra tutto — vedi sotto.
        tipo = "entrata" if entrata_richiesta else "uscita"
        parola_tipo = "entrate" if tipo == "entrata" else "spese"

        # Controllato prima del saldo: una richiesta come "come sta andando
        # l'azienda?" non contiene le parole del saldo, ma "panoramica
        # sulla liquidità" potrebbe — il quadro generale è la lettura più
        # ricca delle due, quindi vince quando entrambe si applicano.
        if any(w in lowered_message for w in self._QUADRO_GENERALE_WORDS):
            return AgentDecision(
                tool="visualize_tool",
                confidence=0.75,
                arguments={"modo": "quadro_generale"},
                reply="Ecco il quadro generale dell'azienda.",
            )

        # Il saldo non ha bisogno di un mese: è sempre "adesso".
        if any(w in lowered_message for w in self._SALDO_WORDS):
            return AgentDecision(
                tool="visualize_tool",
                confidence=0.8,
                arguments={"modo": "saldo"},
                reply="Ecco la liquidità attuale.",
            )

        mesi_trovati: list[tuple[int, int]] = []
        for match in self._MESE_RE.finditer(lowered_message):
            numero_mese = MESI_IT.index(match.group(1)) + 1
            anno = int(match.group(2)) if match.group(2) else date.today().year
            mesi_trovati.append((anno, numero_mese))

        andamento_richiesto = any(w in lowered_message for w in self._ANDAMENTO_WORDS)
        elenco_richiesto = any(w in lowered_message for w in self._ELENCO_WORDS)
        composizione_richiesta = any(w in lowered_message for w in self._COMPOSIZIONE_WORDS)
        spiegazione_richiesta = any(w in lowered_message for w in self._SPIEGAZIONE_WORDS)

        # A differenza degli altri modi, non serve un mese esplicito ("perché
        # sono aumentate le spese?" senza altro vuol dire "questo mese") —
        # controllato prima del "return None" sotto, che altrimenti la
        # scarterebbe per mancanza di un mese riconosciuto.
        if spiegazione_richiesta:
            anno, mese = mesi_trovati[0] if mesi_trovati else (date.today().year, date.today().month)
            return AgentDecision(
                tool="visualize_tool",
                confidence=0.75,
                arguments={"modo": "spiegazione", "tipo": tipo, "periodi": [(anno, mese)]},
                reply=f"Ecco perché le {parola_tipo} sono cambiate.",
            )

        if not mesi_trovati and not andamento_richiesto:
            riferimento_relativo = self._decide_riferimento_relativo(lowered_message, context)
            if riferimento_relativo is not None:
                return riferimento_relativo
            return None  # non assomiglia a una richiesta di visualizzazione

        if elenco_richiesto and mesi_trovati:
            anno, mese = mesi_trovati[0]
            # A differenza degli altri modi, qui il tipo resta non specificato
            # (mostra sia entrate che uscite) a meno che non sia stato chiesto
            # esplicitamente — "i movimenti di luglio" senza altro vuol dire
            # "tutti", non "solo le uscite" come per un grafico di riepilogo.
            tipo_elenco = "entrata" if entrata_richiesta else ("uscita" if uscita_richiesta else None)
            return AgentDecision(
                tool="visualize_tool",
                confidence=0.8,
                arguments={"modo": "elenco", "tipo": tipo_elenco, "periodi": [(anno, mese)]},
                reply="Ecco l'elenco dei movimenti del periodo richiesto.",
            )

        if len(mesi_trovati) >= 2:
            periodo1, periodo2 = mesi_trovati[0], mesi_trovati[1]
            return AgentDecision(
                tool="visualize_tool",
                confidence=0.85,
                arguments={"modo": "confronto", "tipo": tipo, "periodi": [periodo1, periodo2]},
                reply=f"Ecco il confronto delle {parola_tipo} per categoria tra i due periodi.",
            )

        if len(mesi_trovati) == 1:
            return AgentDecision(
                tool="visualize_tool",
                confidence=0.75,
                arguments={
                    "modo": "periodo",
                    "tipo": tipo,
                    "periodi": mesi_trovati,
                    "composizione": composizione_richiesta,
                },
                reply=(
                    f"Ecco la composizione delle {parola_tipo} per categoria del periodo richiesto."
                    if composizione_richiesta
                    else f"Ecco le {parola_tipo} per categoria del periodo richiesto."
                ),
            )

        # "andamento" senza mesi espliciti: andamento mensile sull'anno corrente
        return AgentDecision(
            tool="visualize_tool",
            confidence=0.7,
            arguments={"modo": "andamento", "tipo": tipo, "anno": date.today().year},
            reply=f"Ecco l'andamento mensile delle {parola_tipo}.",
        )

    # Marcatori di "dettatura diretta": quello che segue è già il testo da
    # usare quasi alla lettera come corpo dell'email.
    _MARCATORI_DETTATURA = (":", " dicendo che ", " dicendo ", " scrivendo ")

    # Marcatori di "istruzione indiretta": quello che segue descrive cosa
    # comunicare (es. "...in cui gli dici di ricordarsi il pane"), non è già
    # un messaggio — va avvolto in un frasario minimo per sembrare un'email
    # invece di un frammento di istruzione. Resta un taglia-incolla con
    # template, non una vera riformulazione: quella serve un LLM vero.
    _MARCATORI_ISTRUZIONE = (
        " in cui gli dici di ",
        " in cui le dici di ",
        " in cui gli dici che ",
        " in cui le dici che ",
        " dicendogli di ",
        " dicendole di ",
        " digli di ",
        " dille di ",
        " chiedigli di ",
        " chiedile di ",
    )

    def _estrai_email(self, message: str) -> str | None:
        match = self._EMAIL_RE.search(message)
        return match.group(0) if match else None

    def _estrai_corpo(self, message: str) -> str | None:
        for marker in self._MARCATORI_DETTATURA:
            if marker in message:
                corpo = message.split(marker, 1)[1].strip()
                if corpo:
                    return corpo

        for marker in self._MARCATORI_ISTRUZIONE:
            if marker in message:
                istruzione = message.split(marker, 1)[1].strip().rstrip(".")
                if istruzione:
                    return self._componi_da_istruzione(istruzione)

        return None

    def _componi_da_istruzione(self, istruzione: str) -> str:
        """Avvolge un'istruzione ('ricordarsi di scongelare il pane') in un
        messaggio minimamente leggibile. Template fisso, non generazione:
        non riformula né coniuga verbi — per quello serve un LLM vero
        (vedi OpenAILLMClient)."""
        if istruzione.lower().startswith(("ricord", "di ricord")):
            return f"Ciao,\n\nun promemoria: {istruzione}.\n\nGrazie!"
        return f"Ciao,\n\nti scrivo per questo: {istruzione}.\n\nA presto."


def _istruzioni_sistema(context: dict[str, Any]) -> str:
    """Prompt di sistema condiviso da OpenAILLMClient e GeminiLLMClient —
    include lo schema REALE della tabella candidata quando AgentBrain
    l'ha già trovata (vedi AgentBrain._contesto_decisione, context
    ["tabella_candidata"]), così un LLM vero può scegliere condition_type/
    colonna/modalità ragionando su nomi di colonna veri invece di doverli
    indovinare o limitarsi a un elenco fisso di casi previsti (vedi
    crea_vista_tool/crea_segnalazione_tool — richiesta esplicita
    dell'utente, 3 settembre 2026: "non deve usare template predefiniti ma
    la chat deve capire qualsiasi cosa voglia l'utente")."""
    base = (
        f"Sei l'agente operativo di Cortex per un'azienda del settore "
        f"{context.get('industry', 'generico')}. Usa un tool solo quando l'utente chiede davvero "
        "un'azione o dati finanziari; altrimenti rispondi con una frase breve, senza usare nessun tool."
    )
    tabella_candidata = context.get("tabella_candidata")
    if not tabella_candidata:
        return base
    return (
        f"{base} La tabella più pertinente alla richiesta sembra essere \"{tabella_candidata['nome']}\", "
        f"con queste colonne reali: {', '.join(tabella_candidata['colonne'])}. Se chiami crea_vista_tool o "
        "crea_segnalazione_tool, ragiona su QUALI di queste colonne usare e passale nei parametri giusti — "
        "usa sempre uno di questi nomi esatti, mai un nome inventato o tradotto. Se nessuna colonna di "
        "questa tabella è adatta alla richiesta, ometti i parametri di colonna: verrà tentato un ripiego "
        "automatico."
    )


def _function_declarations() -> list[dict[str, Any]]:
    """I due tool che un LLM vero può richiamare (email_tool, visualize_tool)
    — stessa forma (OpenAPI-style: name/description/parameters, senza il
    wrapper {"type": "function", ...} che solo OpenAI vuole) riusata sia da
    OpenAILLMClient sia da GeminiLLMClient: un solo posto, non due copie che
    rischiano di disallinearsi (già successo una volta — "spiegazione" era
    stato aggiunto al riconoscimento a pattern di StubLLMClient ma non qui,
    quindi un LLM vero non avrebbe mai potuto proporlo)."""
    return [
        {
            "name": "email_tool",
            "description": "Invia un'email tramite l'integrazione Gmail/SMTP dell'utente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_address": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to_address", "body"],
            },
        },
        {
            "name": "crea_vista_tool",
            "description": (
                "Crea (o riusa se esiste già) e mostra subito una Vista salvata e riutilizzabile per una "
                "tabella del database collegato — usalo quando l'utente chiede di vedere/salvare/creare una "
                "vista per un dato aziendale (es. 'mostrami i debitori', 'fammi una vista dei clienti', "
                "'salvami una vista degli ordini'). Se nel messaggio di sistema è indicata una tabella "
                "candidata con le sue colonne REALI, ragiona su quali usare e passa 'mode' + le colonne "
                "giuste (mai un nome inventato: solo uno di quelli elencati) — 'table' va sempre bene, "
                "'calendar' se c'è una data e un titolo sensati, 'cards' se la tabella somiglia a un elenco "
                "di elementi con un titolo (e opzionalmente un sottotitolo/badge). Se non sei sicuro, ometti "
                "'mode': la tabella e la modalità vengono comunque decise da un'euristica automatica."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "termine": {
                        "type": "string",
                        "description": "Il termine o la richiesta originale su cui creare la vista (es. 'debitori').",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["table", "cards", "calendar"],
                        "description": "Opzionale: la modalità scelta ragionando sulle colonne reali della tabella candidata.",
                    },
                    "colonna_data": {"type": "string", "description": "Solo per mode='calendar': nome ESATTO di una colonna data reale."},
                    "colonna_titolo": {"type": "string", "description": "Per mode='calendar'/'cards': nome ESATTO di una colonna testuale reale da usare come titolo."},
                    "colonna_sottotitolo": {"type": "string", "description": "Solo per mode='cards', opzionale: nome ESATTO di un'altra colonna reale."},
                    "colonna_badge": {"type": "string", "description": "Solo per mode='cards', opzionale: nome ESATTO di un'altra colonna reale."},
                },
                "required": [],
            },
        },
        {
            "name": "crea_segnalazione_tool",
            "description": (
                "Crea (o riusa se esiste già) una Segnalazione automatica sui dati collegati. Se nel "
                "messaggio di sistema è indicata una tabella candidata con le sue colonne REALI, scegli tu "
                "'condition_type' e la colonna giusta tra quelle elencate (mai un nome inventato) — non "
                "limitarti a scadenza/soglia se il caso è diverso: 'scadenza_superata' per qualcosa di "
                "scaduto/in ritardo (colonna_data, giorni_tolleranza), 'soglia_numerica' per un valore sopra "
                "o sotto un limite (colonna, operatore '>' o '<', soglia), 'valore_anomalo' per un valore "
                "che si scosta dalla media rispetto agli altri (colonna, opzionale colonna_gruppo per "
                "confrontare solo righe dello stesso gruppo, opzionale soglia_deviazioni). Se non c'è una "
                "tabella candidata nel contesto, o non sei sicuro di quale tipo/colonna usare, passa solo "
                "'termine' (e 'giorni_tolleranza'/'operatore'+'soglia' se il messaggio li rende ovvi): "
                "verrà comunque tentato un riconoscimento automatico più limitato, e l'utente resta libero "
                "di configurarla a mano nella pagina Segnalazioni se il risultato non corrisponde."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "termine": {
                        "type": "string",
                        "description": "Il termine o la richiesta originale (es. 'debitori', 'fatture', 'spese').",
                    },
                    "condition_type": {
                        "type": "string",
                        "enum": ["scadenza_superata", "soglia_numerica", "valore_anomalo"],
                        "description": "Il tipo di condizione, scelto ragionando sulla richiesta e sulle colonne reali disponibili.",
                    },
                    "colonna": {
                        "type": "string",
                        "description": "Per soglia_numerica/valore_anomalo: nome ESATTO di una colonna numerica reale.",
                    },
                    "colonna_data": {
                        "type": "string",
                        "description": "Per scadenza_superata: nome ESATTO di una colonna data reale.",
                    },
                    "operatore": {
                        "type": "string",
                        "enum": [">", "<"],
                        "description": "Solo per soglia_numerica: '>' per maggiore/superiore/sopra, '<' per minore/inferiore/sotto.",
                    },
                    "soglia": {
                        "type": "number",
                        "description": "Solo per soglia_numerica: il valore di confronto.",
                    },
                    "giorni_tolleranza": {
                        "type": "integer",
                        "description": "Solo per scadenza_superata: giorni di tolleranza oltre la scadenza (0 se non specificato).",
                    },
                    "colonna_gruppo": {
                        "type": "string",
                        "description": "Solo per valore_anomalo, opzionale: nome ESATTO di una colonna reale per confrontare solo righe dello stesso gruppo.",
                    },
                    "soglia_deviazioni": {
                        "type": "number",
                        "description": "Solo per valore_anomalo, opzionale: quante deviazioni standard dalla media contano come anomalia (default 2).",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "esplora_tool",
            "description": (
                "Cerca una risposta a una domanda sui dati aziendali collegati che NON riguarda "
                "entrate/uscite/liquidità (per quelle usa sempre visualize_tool) — es. clienti, "
                "fornitori, prodotti, ordini, magazzino, fatture, o qualunque altra tabella del "
                "database collegato, anche se non conosci il nome esatto della tabella. Usalo anche "
                "se non sei sicuro che il dato esista: la ricerca è a costo zero e risponde "
                "onestamente se non trova nulla di pertinente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "termine": {
                        "type": "string",
                        "description": (
                            "Il termine o la richiesta originale dell'utente su cui cercare "
                            "(es. 'fatture', 'quanti fornitori abbiamo')."
                        ),
                    },
                },
                "required": [],
            },
        },
        {
            "name": "visualize_tool",
            "description": (
                "Mostra dati di entrate/uscite/liquidità nella pagina principale, nella forma più "
                "adatta: schede per il saldo attuale, barre per un periodo o un confronto tra due, "
                "barre impilate per la composizione di un periodo, linea per l'andamento mensile di "
                "un anno, tabella per l'elenco dei movimenti, un breve testo per spiegare perché le "
                "spese/entrate di un mese sono cambiate rispetto al precedente, oppure — per una "
                "domanda generica sulla salute dell'azienda, non su un dato specifico — una vista "
                "d'insieme che combina liquidità, cosa è cambiato di recente, previsione di cassa e "
                "segnalazioni aperte tutte insieme (modo='quadro_generale'). Solo per entrate/uscite/"
                "liquidità: per qualunque altro dato aziendale usa esplora_tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "modo": {
                        "type": "string",
                        "enum": ["saldo", "periodo", "confronto", "andamento", "elenco", "spiegazione", "quadro_generale"],
                        "description": (
                            "'quadro_generale': usalo per richieste aperte come 'come sta andando "
                            "l'azienda?', 'dammi un quadro/riepilogo/panoramica generale', 'come va la "
                            "situazione?' — non forzarle in uno degli altri modi, più specifici."
                        ),
                    },
                    "tipo": {"type": "string", "enum": ["entrata", "uscita"]},
                    "periodi": {
                        "type": "array",
                        "description": (
                            "Coppie [anno, mese]: una per 'periodo'/'elenco'/'spiegazione' "
                            "(anno corrente se non specificato), due per 'confronto'."
                        ),
                        "items": {"type": "array", "items": {"type": "integer"}},
                    },
                    "anno": {"type": "integer", "description": "Solo per modo='andamento'."},
                    "composizione": {
                        "type": "boolean",
                        "description": "Solo per modo='periodo': true se l'utente chiede una ripartizione percentuale (barra impilata invece di barre affiancate).",
                    },
                },
                "required": ["modo"],
            },
        },
    ]


class OpenAILLMClient:
    """Client reale (OpenAI, function calling). Scritta per essere pronta
    all'uso ma NON ancora collaudata in questa sessione: nessuna chiave era
    configurata (vedi PLAN.md, 12 agosto 2026). Verificare con una chiamata
    reale prima di affidarcisi in produzione."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._api_key = api_key
        self._model = model

    def decide_action(self, message: str, context: dict[str, Any]) -> AgentDecision:
        from openai import OpenAI  # import differito: pesante e non necessario in modalità stub

        # Timeout esplicito (vedi anche GeminiLLMClient, stessa ragione):
        # senza, una risposta lenta o un rate-limit lato provider blocca la
        # richiesta HTTP a tempo indeterminato invece di far scattare il
        # ripiego su StubLLMClient (AgentBrain._decidi_con_ripiego) — un
        # timeout è a tutti gli effetti un fallimento del provider, non va
        # trattato diversamente da una chiave non valida o una quota esaurita.
        client = OpenAI(api_key=self._api_key, timeout=12.0)
        tools = [{"type": "function", "function": decl} for decl in _function_declarations()]
        messages: list[dict[str, str]] = [{"role": "system", "content": _istruzioni_sistema(context)}]
        # Cronologia dei messaggi recenti (vedi services/conversation_state) —
        # senza, ogni messaggio viene deciso da solo e un riferimento come "e
        # il mese scorso?" non ha modo di essere capito da un LLM vero.
        for turno in context.get("storico", []):
            messages.append({"role": "user" if turno["ruolo"] == "utente" else "assistant", "content": turno["testo"]})
        messages.append({"role": "user", "content": message})

        response = client.chat.completions.create(model=self._model, messages=messages, tools=tools)
        choice = response.choices[0].message
        if choice.tool_calls:
            import json

            call = choice.tool_calls[0]
            arguments = json.loads(call.function.arguments)
            return AgentDecision(tool=call.function.name, confidence=0.85, arguments=arguments, reply=choice.content or "")
        return AgentDecision(tool="none", confidence=0.0, reply=choice.content or "")


# Gemini, quando decide di usare un tool, non genera anche una frase di
# accompagnamento nella stessa risposta (verificato con una chiamata reale:
# un solo "part", solo la function_call, mai testo insieme) — a differenza
# di StubLLMClient, che scrive sempre una frase pronta. Senza questo, la
# bolla di risposta in chat resterebbe vuota anche se il widget compare
# comunque nella pagina principale: confuso, sembra un errore silenzioso.
_REPLY_VISUALIZE = {
    "saldo": "Ecco la liquidità attuale.",
    "elenco": "Ecco l'elenco dei movimenti del periodo richiesto.",
    "confronto": "Ecco il confronto per categoria tra i due periodi.",
    "periodo": "Ecco i dati per categoria del periodo richiesto.",
    "andamento": "Ecco l'andamento mensile richiesto.",
    "spiegazione": "Ecco perché è cambiato.",
    "quadro_generale": "Ecco il quadro generale dell'azienda.",
}


def _reply_di_default(tool: str, arguments: dict[str, Any]) -> str:
    if tool == "visualize_tool":
        return _REPLY_VISUALIZE.get(arguments.get("modo"), "Ecco quello che hai chiesto.")
    if tool == "email_tool":
        return "Ho preparato la bozza dell'email qui sotto: controllala e conferma l'invio."
    if tool == "esplora_tool":
        return "Cerco tra i dati collegati..."
    if tool == "crea_vista_tool":
        return "Trovo la tabella giusta e preparo la vista..."
    if tool == "crea_segnalazione_tool":
        return "Preparo la segnalazione..."
    return ""


class GeminiLLMClient:
    """Client reale (Google Gemini, function calling) — stessa interfaccia e
    stessi due tool di OpenAILLMClient (vedi _function_declarations), a
    differenza di quello VERIFICATA con chiamate reali (vedi PLAN.md, 25
    agosto 2026) prima di diventare quella di default quando GEMINI_API_KEY
    è configurata."""

    def __init__(self, api_key: str, model: str = "gemini-3.6-flash") -> None:
        self._api_key = api_key
        self._model = model

    def decide_action(self, message: str, context: dict[str, Any]) -> AgentDecision:
        import google.generativeai as genai  # import differito: pesante e non necessario in modalità stub

        genai.configure(api_key=self._api_key)
        modello = genai.GenerativeModel(
            self._model,
            tools=[{"function_declarations": _function_declarations()}],
            system_instruction=_istruzioni_sistema(context),
        )
        # Timeout esplicito: verificato dal vivo (3 settembre 2026) che senza
        # questo una risposta lenta/un rate-limit lato Gemini blocca la
        # richiesta HTTP per oltre un minuto invece di far scattare il
        # ripiego su StubLLMClient — un timeout è a tutti gli effetti un
        # fallimento del provider, non va trattato diversamente da una
        # chiave non valida o una quota esaurita (vedi AgentBrain._decidi_con_ripiego).
        risposta = modello.generate_content(
            _contents_da_storico(context.get("storico", []), message),
            request_options={"timeout": 12},
        )

        parte = risposta.candidates[0].content.parts[0]
        function_call = getattr(parte, "function_call", None)
        if function_call and function_call.name:
            arguments = _proto_a_python(function_call.args)
            reply = _reply_di_default(function_call.name, arguments)
            return AgentDecision(tool=function_call.name, confidence=0.85, arguments=arguments, reply=reply)
        return AgentDecision(tool="none", confidence=0.0, reply=risposta.text or "")


_RUOLO_GEMINI = {"utente": "user", "assistente": "model"}


def _contents_da_storico(storico: list[dict[str, str]], message: str) -> list[dict[str, Any]]:
    """Trasforma la cronologia recente (vedi services/conversation_state, già
    passata come lista di dict per non legare llm_client alla dataclass
    Turno) nella forma "contents" multi-turno di Gemini, col messaggio
    corrente come ultimo turno "user" — senza questo, generate_content(message)
    vedeva solo l'ultimo messaggio, senza nessuna nozione di cosa fosse stato
    chiesto prima nella stessa conversazione."""
    contents = [
        {"role": _RUOLO_GEMINI.get(turno["ruolo"], "user"), "parts": [turno["testo"]]}
        for turno in storico
        if turno.get("testo")
    ]
    contents.append({"role": "user", "parts": [message]})
    return contents


def _proto_a_python(valore: Any) -> Any:
    """Gli argomenti di una function_call di Gemini arrivano come strutture
    protobuf (MapComposite/RepeatedComposite), non dict/list nativi Python —
    json non le serializza direttamente. Conversione ricorsiva esplicita
    invece di affidarsi a un dict()/list() superficiale, che lascia gli
    elementi annidati (es. "periodi": [[2026, 7], [2026, 8]]) ancora come
    oggetti protobuf.

    Include anche una correzione non ovvia, trovata solo provando una
    chiamata reale: un campo dichiarato "integer" nello schema (anno, mese)
    torna comunque come float (2026.0) — il tipo Struct di protobuf usato
    da Gemini per gli argomenti non distingue interi da numeri con virgola.
    Un float intero viene quindi convertito a int qui, in un solo posto,
    invece che in ognuna delle funzioni che lo useranno più a valle (dove
    una chiamata come date(2026.0, 7.0, 1) fallirebbe con un TypeError)."""
    if hasattr(valore, "items"):
        return {k: _proto_a_python(v) for k, v in valore.items()}
    if hasattr(valore, "__iter__") and not isinstance(valore, str):
        return [_proto_a_python(v) for v in valore]
    if isinstance(valore, float) and valore.is_integer():
        return int(valore)
    return valore


def get_llm_client() -> LLMClient:
    """Sceglie il client in base alla configurazione: nessuna chiave -> stub
    (gratis, per sviluppo/test), altrimenti il primo provider reale
    configurato. Un cambio di `.env`, non di codice."""
    if settings.GEMINI_API_KEY:
        return GeminiLLMClient(api_key=settings.GEMINI_API_KEY)
    if settings.OPENAI_API_KEY:
        return OpenAILLMClient(api_key=settings.OPENAI_API_KEY)
    return StubLLMClient()
