from __future__ import annotations
import re
from datetime import date
from typing import Any
from app.services.accounting_engine import MESI_IT
from app.services.llm.core import AgentDecision

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

