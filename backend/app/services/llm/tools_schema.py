from typing import Any

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

