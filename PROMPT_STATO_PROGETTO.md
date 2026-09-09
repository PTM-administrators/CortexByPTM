# Prompt di contesto — Stato del progetto "CORTEX Enterprise"

> Incolla tutto questo testo come primo messaggio in una nuova chat con Claude per farle capire a che punto è il progetto, senza dover rispiegare tutto da capo.

---

## 1. Cosa sto costruendo

Sto sviluppando **CORTEX Enterprise**, una piattaforma SaaS B2B multi-tenant di contabilità/operations, situata in locale in `/Users/gabriele/Desktop/Cortex`. Il progetto NON è un repository git (nessun `.git`).

**Stack tecnico:**
- **Backend**: FastAPI + SQLAlchemy 2.0 (Core, non ORM puro) + Alembic (migrazioni) + SQLite (database "core" di Cortex, dati applicativi: utenti, organizzazioni, integrazioni, regole...) + pyodbc/mssql per connettersi ai database ERP dei clienti (es. SQL Server).
- **Frontend**: React 18 + Vite + Tailwind CSS + recharts (grafici) + lucide-react (icone) + Axios.
- **LLM per la chat**: integrazione con Google Gemini (con fallback su OpenAI se configurato, e un fallback finale "stub" pattern-matching senza LLM se tutto il resto fallisce).

**Server di sviluppo (di solito già avviati durante le sessioni precedenti):**
- Backend: `uvicorn` su `http://localhost:8000` (con `--reload`)
- Frontend: `vite` su `http://localhost:5173`

---

## 2. Il modello di business e i due clienti-ancora

Cortex è pensato per servire **molti clienti eterogenei contemporaneamente** — alcuni con un vero ERP collegato, altri senza. Durante lo sviluppo ho usato due clienti reali come banco di prova, con dati e schemi reali (non mock):

1. **Casa Diocesana di Sampeyre** — organizzazione no-profit, senza un vero ERP. Ha uno schema SQLite semplice fatto in casa (tabella `movimenti` con entrate/uscite).
2. **Trevalli** — azienda vera che usa l'ERP **Arca** su **SQL Server**, con uno schema enorme e reale: **372-380 tabelle** (es. `CGMovR`, `CGMovT`, `CGDatiFatturaR`, `CGLiqRighe`, `orsDO2`, `orsCF2`...).

Il motore contabile è quindi **duale**: `accounting_engine.py` (profilo Sampeyre) e `accounting_engine_arca.py` (profilo Arca), con le stesse firme di funzione (`compute_saldi`, `compute_spese_per_categoria`, `compute_andamento_mensile`, `ultimo_periodo_con_movimenti`...). Una funzione `_motore_contabile()` / `_e_arca()` rileva automaticamente lo schema e sceglie il motore giusto — chi chiama queste funzioni non deve sapere quale profilo è in uso.

**Credenziali di test già funzionanti**, usate per verifiche durante lo sviluppo:
- Trevalli: `peanogabriele70@gmail.com` / `Trevalli2026!`
- (c'è anche un utente collegato a Sampeyre, verificare in `PLAN.md`/DB se serve)

---

## 3. Il percorso di sviluppo — come sono arrivato qui (in ordine)

Il mio approccio di lavoro con Claude è stato molto iterativo e critico: ho continuamente testato le funzionalità proposte e segnalato problemi concreti invece di accettare rassicurazioni generiche. Le tappe principali, in ordine cronologico:

### 3.1 Base contabile e chat
- Saldi banca e comandi chat per il profilo Arca (Trevalli).
- Bug: "cosa è cambiato" mostrava sempre 0 per Trevalli → causa: la logica usava la data di calendario di oggi, ma i dati reali di Arca si fermano a **dicembre 2020** (mentre "oggi" in sessione è ~agosto 2026). **Fix**: pattern "ultimo periodo con movimenti" — tutte le feature che devono riflettere lo "stato attuale" usano l'ultimo periodo con dati reali (`ultimo_periodo_con_movimenti()`), non la data di calendario.
- Riorganizzazione della sezione Contabilità in tab.

### 3.2 La crisi di validazione del prodotto (importante!)
A un certo punto ho fermato lo sviluppo e ho messo in discussione il valore del prodotto:
> "ok pero io trovo che non sia un prodotto vendibile alle aziende ce a cosa dovrebbe servire?"

Ho chiarito che voglio servire **molti clienti eterogenei** (alcuni con ERP, alcuni senza) — un prodotto versatile per tutti, non solo per chi ha un ERP.

Poi ho fatto notare un problema concreto: la feature "Portfolio" (vista aggregata su tutti i clienti) serve **a me come fornitore**, non ai miei clienti aziendali. Ho chiesto esplicitamente: *"ma i miei clienti alle aziende a cosa dovrebbe servire"*.

**Risoluzione**: distinzione netta tra:
- feature che duplicano cose che l'ERP del cliente fa già (es. Data Explorer CRUD generico, "modelli pronti" che ricalcano report nativi di Arca) → poco valore, ridondanti
- feature davvero differenzianti: notifiche proattive, spiegazioni automatiche, **azioni pronte** (bozze di email/solleciti auto-generate), analisi automatica cross-tabella

Quando mi è stata data la scelta tra "il sistema si limita a notificare" e "il sistema prepara da solo il sollecito a un fornitore/cliente scaduto", ho scelto la seconda: **"Non basta, serve qualcosa di più concreto"**.

### 3.3 Segnalazioni + Azioni Pendenti (auto-drafted actions)
- `alert_engine.py`: motore di regole (`valuta_regola_con_riga`, `valuta_regola`, `valuta_condizione`, `valuta_tutte_le_regole`) condiviso tra `api/alerts.py`, dashboard portfolio e `notifiche.py`.
- Nuovo modello `AzionePendente` (organization_id, origine, to_address, subject, body, stato: in_attesa/inviata/rifiutata) — quando una regola scatta E ha un `azione_template` collegato, `notifiche.py._prepara_azione_se_configurata()` genera automaticamente una bozza di azione (es. email di sollecito) pronta da confermare o scartare, invece di limitarsi a notificare.
- Frontend `Segnalazioni.jsx`: sezione "Azioni pronte da confermare" con bottoni Conferma/Scarta, più un'anteprima live (con debounce) di cosa farebbe la regola PRIMA di salvarla (endpoint `POST /alerts/anteprima`, non serve salvare la regola per vedere l'anteprima).

### 3.4 Usabilità (seconda crisi)
Dopo aver costruito Segnalazioni, ho detto chiaramente:
> "esatto ce la parte di segnalazioni è molto utile pero è troppo difficile da usare. Inoltre un altro problema che ho notato è che l'amministratore di un'azienda non può sapere quali grafici la chat può mostrare e quali no"

**Fix**: in `AgentChat.jsx`, bottone sempre visibile "Cosa posso chiederti?" con pannello di aiuto categorizzato (`CATEGORIE_AIUTO`), che include anche i nomi reali delle Viste salvate dall'utente (fetch dinamico da `GET /views`), così l'utente sa esattamente cosa può chiedere.

### 3.5 Integrazione Gemini per una vera chat LLM
Ho fornito chiavi API reali di Gemini (mischiate a variabili boilerplate Next.js/Capacitor non pertinenti) chiedendo se si potevano integrare per avere una chat vera (non solo pattern-matching).

**Cosa è stato costruito** (`llm_client.py`):
- `_function_declarations()`: schema condiviso in stile OpenAPI per i tool `email_tool`/`visualize_tool`, riusato sia da `OpenAILLMClient` che dalla nuova `GeminiLLMClient`.
- `GeminiLLMClient`: usa `google.generativeai`, function-calling nativo di Gemini.
- `get_llm_client()`: preferisce Gemini > OpenAI > `StubLLMClient` (pattern-matcher gratuito) in base a quale API key è configurata in `.env`/`config.py`.

**Bug reali scoperti e risolti durante l'integrazione Gemini:**
1. Il modello `gemini-2.0-flash` non esiste più (404) → usato `gemini-3.6-flash` (nome suggerito dal messaggio di errore stesso dell'API).
2. Gli argomenti delle function-call di Gemini arrivano come protobuf Struct con **tutti i numeri come float** (es. `2026.0` invece di `2026`), il che rompeva `date(2026.0, 7.0, 1)` → fix con `_proto_a_python()`, un convertitore ricorsivo protobuf→Python nativo che converte i float interi in int.
3. Gemini omette i campi opzionali dello schema (`periodi`, `anno`) quando l'utente non specifica mese/anno → causava KeyError/500 reali → fix con `_periodo_richiesto()`, un helper con fallback al mese corrente, usato in 3 punti di `agent_brain.py`.
4. **Quota gratuita Gemini: 20 richieste/giorno/modello** (limite hard, confermato letteralmente esaurendo la quota durante i test, errore reale `ResourceExhausted: 429`) → fix con `AgentBrain._decidi_con_ripiego()`: qualunque fallimento del client LLM reale (quota/rete/auth) fa fallback silenzioso su `StubLLMClient` per quel singolo messaggio, senza mai mostrare un errore 500 grezzo all'utente.

### 3.6 "Quadro generale" — composizione invece di template fissi
Ho detto:
> "ok, stiamo procedendo bene, pero trovo ancora troppo poco utile la possibilita di visionare grafici tramite la chat. Ce di per se sono solo dei template gia fatti io vorrei che invece in base a cio che gli viene scritto si possa vedere un tutto tondo dell'azienda"

**Soluzione**: invece di un vero loop agentico multi-turno con tool-calling (che avrebbe consumato la scarsa quota giornaliera di Gemini), è stato costruito un nuovo modo `quadro_generale` che **compone in una singola chiamata LLM** più fonti dati già pronte lato server: saldi + spiegazione ("cosa è cambiato") + previsione di cassa + segnalazioni attive, tutte in un unico widget (`QuadroGeneraleWidget` nel frontend).

Prima di questo è stato anche costruito `previsione.py`: `previsione_liquidita()` proietta la liquidità futura basandosi sul flusso di cassa medio mensile netto (entrate - uscite), partendo dall'ultimo periodo con movimenti reali, con un `avviso` se la proiezione va in negativo.

### 3.7 Analisi automatica — zero configurazione (l'ultima feature costruita)
Ultima richiesta prima di "avvia cortex":
> "ok, pero le viste e le segnalazioni son troppo difficili da programmare. Cortex deve essere un software che lo fa in automatico che mostra grafici tabelle e andamenti"

Alla domanda su come vuole che funzioni, ho scelto: **"Analizzare ogni tabella collegata e mostrare grafici/andamenti da solo"**.

**Costruito**: `services/analisi_automatica.py` — analisi automatica zero-config di QUALUNQUE database collegato (non solo schemi contabili riconosciuti), con pipeline a 3 livelli per restare veloce anche su un ERP reale da 372 tabelle:
1. `COUNT(*)` economico su tutte le tabelle (per scartare le tabelle vuote/piccole)
2. ispezione economica dei metadati delle colonne (via `Inspector.get_columns()`, molto più economico della reflection completa `Table(autoload_with=...)`)
3. query dati vera e propria, solo sulle poche tabelle superstiti (limitata a 3000 righe, ultimi 12 mesi)

Con caching in-process (30 minuti TTL) per evitare di ripetere la scansione.

Nuova pagina frontend `/andamenti` (`Andamenti.jsx`): mostra una griglia di grafici (uno per tabella rilevante trovata), riusando il widget "line" già esistente — zero nuovo codice grafico frontend.

**Bug reali scoperti e risolti durante questa feature:**
- Prima versione: **75.62 secondi** di runtime → causa: reflection completa (`Table(autoload_with=engine)`) per ogni tabella candidata, molto costosa su tabelle larghe reali (es. `CGMovR`: 15.12s, `CGLiqRighe`: 15.94s) → fix: sostituita con costrutti leggeri `sqlalchemy.table()/column()` (nessun round-trip di metadati verso il DB) → sceso a **2.79-2.92 secondi**.
- Colonne scelte senza senso: `TimeIns` (timestamp di audit, non data di business) scelta come "data"; `ContoMerceSpesa` (un campo flag/booleano) scelta come "numero" perché "spesa" faceva match come SOTTOSTRINGA → fix: lista di esclusione nomi-data di audit (`_NOMI_DATA_ESCLUSI`), e match sulle colonne numeriche cambiato da sottostringa a **prefisso** (`startswith`).
- Su Sampeyre (SQLite), **tutte le righe venivano scartate silenziosamente**: le query leggere senza reflection completa non ottengono la coercizione automatica stringa→data di SQLAlchemy (che normalmente viene dal conoscere il tipo dichiarato della colonna via reflection completa) — SQLite salva le colonne DATE come TEXT, quindi il driver restituiva stringhe Python grezze, e il controllo originale `isinstance(d, date)` scartava silenziosamente ogni riga, facendo sembrare che Sampeyre non avesse "nessun andamento" nonostante avesse 13 movimenti reali multi-mese. Fix: nuovo helper `_a_data(valore)` che gestisce oggetti con `.date()`, `date` nativi, E stringhe ISO (`date.fromisoformat(valore[:10])`).
- Valori sentinella di date future (es. `CS.DataInizioAmmortamento` con una data "2070") inquinavano la finestra "ultimi 12 mesi" → fix: filtro che scarta `d > oggi`.
- Colonne sempre a zero mostrate come se fossero un "andamento" significativo (es. `CS.ImportoMassimoDetraibile`, genuinamente sempre zero nei dati reali) → fix: filtro esplicito che ritorna `None` se tutti i valori del periodo sono zero.

**Verificato su entrambi i clienti reali:**
- Sampeyre → 1 tabella rilevata (`movimenti`, dati reali gen-ago 2026)
- Trevalli/Arca → 3 tabelle rilevate su 372 scansionate (CGMovR/ImportoV, CGMovT/ImportoE, CGDatiFatturaR/Importo), 2.8s la prima volta / 20ms con cache

---

## 4. Multi-tenancy (accesso multi-organizzazione)

- Nuovo modello `Membership` (user_id ↔ organization_id, many-to-many, unique constraint).
- `User.organization_id` reinterpretato come "organizzazione attualmente attiva" (nessuna modifica alle firme degli endpoint esistenti, dato che tutto già leggeva questo campo).
- Nuovi endpoint in `api/auth.py`: `GET /auth/my-organizations`, `POST /auth/switch-organization`, `POST /auth/join-organization`, `POST /auth/create-organization`.
- Frontend: selettore organizzazione nella Topbar (visibile solo se `organizations.length > 1`), pagina `Portfolio.jsx` ("I miei clienti") che aggrega dati da tutte le organizzazioni a cui un utente ha accesso (endpoint `GET /dashboard/portfolio`).

**Problema noto MA deliberatamente non prioritario**: la pagina Team non mostra un consulente/admin aggiunto a un'organizzazione cliente tramite Membership (mostra solo utenti la cui organizzazione "di casa" combacia). Segnalato più volte, l'utente ha sempre scelto altre priorità.

---

## 5. File chiave (percorsi assoluti, per orientarsi velocemente)

**Backend — servizi core:**
- `backend/app/services/analisi_automatica.py` — analisi automatica zero-config (l'ultima feature, vedi 3.7)
- `backend/app/services/accounting_engine.py` / `accounting_engine_arca.py` — motore contabile duale
- `backend/app/services/agent_brain.py` — orchestrazione della chat/agente, dispatch dei "modi" (saldo/periodo/confronto/andamento/elenco/spiegazione/quadro_generale), fallback LLM
- `backend/app/services/llm_client.py` — client OpenAI/Gemini/Stub, function declarations condivise
- `backend/app/services/alert_engine.py` — motore regole di segnalazione
- `backend/app/services/notifiche.py` — genera segnalazioni E azioni pendenti
- `backend/app/services/previsione.py` — previsione di cassa
- `backend/app/services/narrazione.py` — "cosa è cambiato" (spiegazioni automatiche)
- `backend/app/services/db_engine.py` — Engine condiviso + cache tabelle reflected (TTL 600s)
- `backend/app/services/industry_rules.py` — configurazione nav/menu per settore
- `backend/app/services/integration_providers.py` — catalogo provider integrazioni

**Backend — API:**
- `backend/app/api/integrations.py`, `alerts.py`, `azioni_pendenti.py`, `auth.py`, `dashboard.py`

**Backend — modelli:**
- `backend/app/models/membership.py`, `alert_rule.py`, `azione_pendente.py`

**Frontend — pagine:**
- `frontend/src/pages/Andamenti.jsx` — pagina "Andamenti" (analisi automatica)
- `frontend/src/pages/Segnalazioni.jsx` — Segnalazioni + Azioni pendenti
- `frontend/src/pages/Portfolio.jsx` — vista multi-cliente
- `frontend/src/pages/Dashboard.jsx`, `Integrations.jsx`

**Frontend — componenti:**
- `frontend/src/components/widgets/WidgetCanvas.jsx` — rendering di tutti i widget dinamici, incluso `QuadroGeneraleWidget`
- `frontend/src/components/chat/AgentChat.jsx` — chat con pannello "Cosa posso chiederti?"
- `frontend/src/context/AuthContext.jsx` — stato auth, config settore, organizzazioni
- `frontend/src/App.jsx` — routing

**Documentazione del progetto:**
- `PLAN.md` — aggiornato continuamente dopo ogni feature verificata, con sezioni dettagliate "✅ verificato" (numeri e tempi reali citati) — **consultare questo file per lo storico completo e i dettagli che non stanno in questo prompt**.

---

## 6. Metodo di lavoro / aspettative con cui ho lavorato finora

Queste sono convenzioni che ho imposto de facto durante lo sviluppo e che vanno rispettate anche in futuro:

1. **Nessun mock accettato.** Ogni verifica è stata fatta con dati reali, chiamate API reali, interazione browser reale, incrociando numeri con cifre indipendentemente note come corrette (es. il totale "fornitori da pagare" verificato contro la cifra "Debiti verso fornitori" del bilancio).
2. **Testo critico, non assertivo.** Ho spesso interrotto lo sviluppo per contestare il valore reale di una feature ("non è vendibile", "troppo difficile da usare") — le risposte accomodanti senza sostanza non bastano, serve iterare fino a una soluzione concreta.
3. **Verifica sempre su ENTRAMBI i clienti-ancora** (Sampeyre e Trevalli) quando una feature tocca la logica contabile, perché hanno schemi/scale molto diversi (SQLite piccolo vs SQL Server con 372 tabelle) e i bug emergono quasi sempre solo su uno dei due.
4. **Timestamp**: attenzione alla differenza tra "oggi" di calendario e "ultimo periodo con dati reali" — molti bug sono nati da questa confusione (specialmente su Trevalli, i cui dati reali si fermano a dicembre 2020).

---

## 7. Problemi noti, non bloccanti, mai risolti (per completezza)

- Pagina Team non mostra membri aggiunti via Membership ad altre organizzazioni (vedi punto 4).
- "Scadenzario fiscale automatico" (da CGLiqIva/periodicità IVA) proposto insieme alla previsione di cassa ma mai costruito — l'utente ha scelto prima la previsione di cassa.
- Due integrazioni demo (Immobiliare id=5, Barbiere id=6) hanno connection string SQLite verso percorsi scratchpad di sessioni precedenti ormai inesistenti (stesso problema già risolto una volta per "Debitori", id=3, ricreando il file e aggiornando la connection string nel DB) — non ancora risolto per queste due, non blocca nulla al momento.

---

## 8. Stato al momento dell'ultimo checkpoint

Sia il backend (`uvicorn`, porta 8000, `--reload`) che il frontend (`vite`, porta 5173) erano attivi e funzionanti, verificati con la schermata di login raggiungibile su `http://localhost:5173`. L'ultima feature costruita e verificata su entrambi i clienti reali è stata "Andamenti" (analisi automatica, vedi punto 3.7). Nessun problema tecnico aperto in sospeso da quella sessione: l'ultima richiesta esplicita ("avvia cortex") era già stata soddisfatta.

---

## 9. Cosa chiedere a Claude in questa nuova chat

Incollando questo prompt, puoi chiedere a Claude di:
- Riprendere da dove eravamo rimasti e proporre la prossima feature/priorità.
- Rivedere lo stato attuale del codice rispetto a questa descrizione (potrebbe essere cambiato nel frattempo).
- Aiutarti a decidere tra le opzioni ancora aperte (scadenzario fiscale, fix pagina Team, pulizia integrazioni demo, o qualcos'altro).
- Leggere `PLAN.md` nella cartella del progetto per i dettagli tecnici completi non riportati qui per brevità.
