# Piano di Progetto — CORTEX Enterprise (+ modulo Sampeyre)

Ultimo aggiornamento: 2026-08-11

## 0. Origine di questo piano

Due documenti sono confluiti in questo progetto:

1. **Spec CORTEX Enterprise** — piattaforma SaaS B2B multi-tenant "camaleontica": UI e dati si
   adattano al settore (`industry`) dell'azienda loggata, con un Hub Integrazioni per le
   credenziali esterne e un Agente AI (LangChain) che esegue azioni reali.
2. **Piano di Progetto — Software Casa Diocesana di Sampeyre** (docx del 3 agosto 2026,
   decisioni prese con Andrea) — un gestionale di contabilità (Prima Nota, cespiti/ammortamenti,
   bilancio civilistico art. 2425 c.c., IVA, riconciliazione bancaria, IA per fatture/scontrini e
   assistente conversazionale) per sostituire un Excel a 61 fogli.

Decisione presa insieme (11 agosto 2026): **Sampeyre non è un progetto separato**, è il primo
settore verticale reale di Cortex (`industry = "nonprofit_finance"`). Tutte le funzionalità del
docx diventano moduli di quel settore, riutilizzando l'architettura multi-tenant invece di un
programma desktop a sé stante.

## 1. Stato di partenza (non si parte da zero)

In `/Users/gabriele/Desktop/Cortex` esiste già uno scaffold funzionante:

| Componente | Stato |
|---|---|
| Backend FastAPI, struttura cartelle come da spec | ✅ |
| Modelli `User` (con `industry`), `Integration` | ✅ |
| Auth JWT (register/login/`get_current_user`) | ✅ |
| DB | SQLite dev, Postgres pronto ma commentato in `requirements.txt` |
| Alembic | configurato, **nessuna migrazione creata** (tabelle da `create_all`) |
| `industry_rules.py` | 4 settori demo, nessuno per la finanza no-profit |
| API `integrations.py` | ❌ **router mancante** (la pagina `Integrations.jsx` non ha endpoint) |
| `agent_brain.py` | routing a parole chiave, **non** un vero agente LLM/LangChain |
| Tool (`email_tool`, `db_connector`, `scraper_tool`) | funzionanti, generici |
| Frontend (Login, Register, Dashboard, Sidebar, Topbar, AgentChat) | ossatura presente, Sidebar **statica** (non dipende da `industry`) |

`sito1` (altro progetto sul Desktop) resta fuori da questo lavoro, non viene toccato.

## 2. Decisioni architetturali confermate (11 agosto 2026)

- **Dati dei tenant vivono fuori dal DB interno di Cortex.** L'Hub Integrazioni (`Integration` +
  `db_connector.py`) è il meccanismo generico con cui un'azienda collega il proprio DB/API
  esistente; Cortex fa da layer di visualizzazione intelligente e di agente sopra quei dati.
  Per Sampeyre, che parte da un Excel, Cortex provisiona un database dedicato e isolato (non
  condiviso con altri tenant) con lo schema Prima Nota/Cespiti pronto — stesso meccanismo di
  qualsiasi altra azienda, nessun trattamento speciale.
- **DB interno di Cortex**: resta SQLite per ora (nessuna migrazione a Postgres a breve). Le
  connessioni ai DB dei singoli tenant sono stringhe indipendenti, quindi non c'è conflitto.
- **LLM**: OpenAI come provider di partenza (chiave già presente in `.env`), dietro
  un'astrazione LangChain per poter cambiare provider senza refactoring. Due livelli di
  modello: economico per task frequenti/semplici (categorizzazione, spiegazioni), full/vision
  per task che richiedono qualità (lettura fatture/scontrini, assistente conversazionale,
  bilanci commentati).
- **Punto ancora aperto, non bloccante**: il docx Sampeyre prevedeva "programma desktop con
  dati in locale" come requisito confermato con Andrea. Passando a Cortex (cloud, dati sul DB
  dedicato del tenant) si perde l'uso realmente offline. Compensato con: export PDF/Excel
  on-demand, backup automatico in cloud (già richiesto anche nel docx), e possibilità di
  collegare/scaricare il DB dedicato con strumenti esterni. Da confermare con Andrea prima del
  rilascio finale a Sampeyre, ma non blocca lo sviluppo delle altre fasi.

## 3. Fasi di sviluppo

### Fase A — Consolidamento fondamenta Cortex ✅ (11 agosto 2026)
- Router `api/integrations.py`: CRUD completo (list/create/update/delete), catalogo
  provider dinamico (`GET /integrations/providers`), credenziali cifrate a riposo
  (Fernet, chiave derivata da `SECRET_KEY`) e mascherate in ogni risposta API.
- Sidebar/dashboard dinamiche: `industry_rules.py` espone `nav_items`+`icon` per
  settore, letti da `AuthContext`/Sidebar via `lucide-react` invece di un menu
  fisso. Aggiunto il settore `nonprofit_finance` ("Finanza No-Profit") con widget
  placeholder (saldo cassa/banca, movimenti mese, cespiti da ammortizzare).
- Prima migrazione Alembic reale (`24cb88b58b4d`), applicata; `main.py` non usa
  più `create_all` allo startup, Alembic è la fonte di verità dello schema.
- **Correzioni collaterali scoperte durante la verifica**: il `.venv` del repo era
  un venv Windows inutilizzabile su questo Mac (ricreato con Python 3.12 via
  Homebrew); `DATABASE_URL` relativo produceva un file `.db` diverso a seconda
  della cartella da cui si lanciava il processo (ora ancorato a `backend/` in
  `database.py`); permessi/quarantena macOS su `node_modules` impedivano
  l'avvio di Vite (corretti); sfondo nero in dark mode di sistema per
  mancanza di `background-color` su `body` (corretto, ma la vera dark mode
  della spec resta da fare).
- Verificato end-to-end nel browser: registrazione con settore "Finanza
  No-Profit" → dashboard con widget corretti → creazione integrazione
  `sql_erp` con connection string → credenziali confermate cifrate nel
  database (non in chiaro) → eliminazione integrazione.

### Fase B — Motore generico di esplorazione dati (rivisto 11 agosto 2026)
Decisione (11 agosto): niente pagine React su misura per Sampeyre. Fase B costruisce
una capacità **generica**, utile a qualunque tenant, non solo alla finanza no-profit.
Una UI dedicata resta possibile più avanti (Fase B2, solo se il motore generico si
rivela insufficiente), ma non è il punto di partenza.

- **Introspezione + CRUD generico su DB collegati**: dato un `Integration` di tipo
  "database" (`sql_erp`/`custom_db`/nuovo `cortex_managed_db`), nuovi endpoint
  (`api/data_explorer.py`) per: elencare tabelle e colonne, leggere righe (paginate,
  filtrabili), creare/aggiornare/eliminare una riga — tutto tramite reflection
  SQLAlchemy (query parametrizzate, nomi tabella/colonna vincolati a quelli
  introspezionati, mai stringhe concatenate) così funziona su **qualsiasi** schema,
  non solo quello di Sampeyre.
- **Provisioning di un DB per chi non ne ha uno**: nuovo provider
  `cortex_managed_db` — Cortex crea un database dedicato al tenant (isolato dagli
  altri) invece di richiedere una connection string esterna. Stesso meccanismo di
  "collega il tuo DB", solo che il DB lo ospita Cortex. Con supporto opzionale a
  **template** (schema + dati di partenza già pronti): il primo template è
  `nonprofit_accounting` (tabelle Categoria/Movimento/Cespite/FondoProgetto/
  SogliaBudget, seed delle categorie del docx) — riutilizzabile da qualunque
  associazione/diocesi con esigenze simili, non solo da Sampeyre.
- **Frontend `DataExplorer.jsx`** (generico, in nav per tutti i settori, non solo
  `nonprofit_finance`): scegli un'integrazione di tipo database → vedi le tabelle →
  vedi/aggiungi/modifica/elimina righe, con un form generato dai tipi di colonna
  (testo, numero, data...). Un'azienda e-commerce con un ERP collegato usa la
  stessa identica schermata per i suoi ordini.
- **Sampeyre concretamente**: provisioning di un DB dal template
  `nonprofit_accounting`, registrato come sua integrazione. A quel punto Andrea può
  già inserire/vedere movimenti e cespiti reali attraverso il Data Explorer — nessun
  calcolo automatico ancora (arriva in Fase C), ma i dati sono reali e strutturati
  correttamente.

**Fase B completata (11 agosto 2026).** Bug trovato e corretto durante la verifica:
i valori dal form arrivano sempre come stringhe, ma SQLAlchemy/SQLite richiedono
tipi Python reali (date, Decimal) sulle colonne tipizzate — aggiunta una
conversione automatica in `data_explorer.py` basata sul tipo di colonna
introspezionato. Scoperto anche che i default "lato Python" di SQLAlchemy
(`default=...`) non si applicano quando una tabella viene letta per reflection
(il caso normale di un motore generico): corretti in `db_templates.py` con
`server_default`, che è scritto nello schema reale del database.

Verificato end-to-end: provisioning DB Sampeyre (58 categorie seedate) →
creazione/modifica/eliminazione di un Movimento reale tramite il Data Explorer →
**stesso identico Data Explorer** collegato a un secondo database esterno con
uno schema completamente diverso (tabella "ordini" di un finto ERP e-commerce,
provider `custom_db`) → lettura corretta senza alcuna modifica al codice. Il
requisito "Cortex deve gestire anche le altre aziende, non solo Sampeyre" è
verificato, non solo dichiarato.

### Fase C — Motore contabile ✅ core completato e verificato (12 agosto 2026)
Costruito come logica di dominio specifica del settore "Finanza No-Profit"
(non generica come il Data Explorer di Fase B — previsto, deciso insieme):
`app/services/accounting_engine.py` opera sullo schema del template
`nonprofit_accounting`, esposto pubblicamente da `db_templates.py` come
contratto condiviso. Nuova voce di menu "Contabilità", visibile solo per
questo settore (`industry_rules.py`).

Endpoint (`GET /integrations/{id}/accounting/...`): `saldi`, `ammortamenti`,
`iva`, `budget`, `anomalie`, `bilancio`. Pagina frontend `Contabilita.jsx`
mostra tutto in un'unica vista.

**Verificato con dati reali inseriti via API** (13 movimenti su 8 mesi, 1
cespite, 1 soglia budget) e confrontati a mano: saldo Banca, Conto Economico
per gruppo, ammortamento annuo, IVA a debito/credito, soglia budget superata
(bolletta anomala da 900€ contro soglia 200€) e anomalia statistica rilevata
correttamente (z-score) — tutti i numeri tornano esatti sia via API sia nella UI.

Due correzioni emerse in Fase B e riutilizzate qui: valori tipizzati
correttamente (date/Decimal) e default `anno`/`mese` calcolati a runtime, non
congelati all'avvio del server (bug simile a quello di `date.today()` come
default statico di una funzione, evitato di proposito).

**Riconciliazione bancaria ✅ completata e verificata (12 agosto 2026).**
`app/services/bank_reconciliation.py`: carichi un CSV dell'estratto conto
(colonne data/importo/descrizione, nomi ed formati flessibili — date
IT/ISO, importi con virgola o punto decimale), abbinato ai Movimenti su conto
Banca non ancora riconciliati per importo esatto + data entro tolleranza
(default 3 giorni). I movimenti abbinati vengono marcati `riconciliato` nel
database (colonna aggiunta al template; per il db Sampeyre già esistente
applicata con un ALTER TABLE mirato, non un sistema di migrazione generico).

Verificato con un estratto conto vero (multipart reale, non un mock): 3 righe
abbinate correttamente nonostante formati diversi (data italiana, ISO,
importo con virgola, scarto di 1-2 giorni), 1 riga senza corrispondenza
segnalata, e i movimenti restanti mostrati come "in Prima Nota ma non
nell'estratto". Verificata anche l'idempotenza: ricaricando lo stesso file,
zero nuovi abbinamenti (i movimenti già riconciliati non vengono riproposti).
UI in `Contabilita.jsx` confermata con un upload simulato via `DataTransfer`
(il tool di automazione browser non supporta upload nativo di file).

### Fase D1 — Agente reale (esecuzione tool + conferma email) ✅ verificato (12 agosto 2026)
Decisione (12 agosto): si costruisce tutta la Fase D fin da subito con un
client LLM finto (`app/services/llm_client.py`, `StubLLMClient`), a costo
zero — `OPENAI_API_KEY` è vuota, nessuna chiamata a pagamento è possibile.
Passare a un provider reale (`OpenAILLMClient`, già scritta ma non collaudata)
è un cambio di `.env`, non di codice (`get_llm_client()`).

- `agent_brain.py` ricostruito: non descrive più le azioni, le esegue. Le
  azioni di sola lettura (ricerca web) partono subito; le azioni con effetti
  verso l'esterno (invio email) diventano un'"azione pendente"
  (`agent_state.py`, in memoria) che l'utente deve confermare esplicitamente
  in chat prima che parta davvero (`POST /api/agent/confirm/{id}`).
- `email_tool.py` reso più robusto: STARTTLS e AUTH usati solo se il server
  li offre davvero (non tutti i relay SMTP li richiedono) — utile in generale
  e necessario per poter testare senza un vero account Gmail.
- **Verificato con un invio reale**, non un mock: server SMTP di debug locale
  (`aiosmtpd`) collegato come integrazione "gmail" di test → comando in chat
  ("manda una email a... dicendo:...") → bozza mostrata con conferma
  obbligatoria → confermata dalla UI → il server SMTP ha ricevuto davvero il
  messaggio via un vero scambio SMTP, con From/To/Subject/corpo corretti letti
  direttamente dal log del server. Verificato anche che, prima della conferma,
  nessuna email risulti inviata. Integrazione e server di test rimossi dopo la verifica.

**Sequenziato apposta dopo** (non bloccante): categorizzazione automatica con
soglia di fiducia, lettura fatture/scontrini, assistente conversazionale sui
dati reali, bilanci commentati — le funzioni che richiederanno davvero un LLM
a pagamento quando si vorrà collaudarle sul serio.

**Limite noto, accettato di proposito (12 agosto 2026):** `StubLLMClient`
riconosce frasi indirette tipo "in cui gli dici di ricordarsi il pane" e le
avvolge in un frasario minimo (`_componi_da_istruzione`), ma resta un
taglia-incolla con template, non una vera riformulazione nel tono richiesto —
quello serve un LLM vero. Deciso di restare sul gratuito per ora.

### Vista generata dall'agente ("visualize_tool") ✅ completato e verificato (16 agosto 2026)
Idea dell'utente, poi ampliata due volte nella stessa direzione: (1) scrivere
in chat "mostrami le spese di luglio confrontate con maggio" e ottenere un
grafico vero, non solo testo; (2) "tutti i tipi di grafici", non solo barre;
(3) tabelle e schede oltre ai grafici, e soprattutto **mostrati nella pagina
principale, non nella finestra di chat** — la chat resta il comando, la
pagina principale è dove compare il risultato. Stesso compromesso già usato
per l'email: riconoscimento a pattern (gratis, `StubLLMClient`) invece di
comprensione libera del linguaggio, scelto esplicitamente dall'utente.

- **Scelta della forma guidata dalla skill `dataviz`, non a piacere**: per la
  "composizione" di un periodo si usa una **barra impilata orizzontale**, non
  una torta — la guida la sconsiglia esplicitamente con nomi di categoria
  lunghi come i nostri, e propone la barra impilata come forma corretta per
  "parte sul tutto". Spiegato esplicitamente all'utente prima di procedere.
- `accounting_engine`: aggiunta `list_movimenti` (righe grezze per la vista a
  tabella), oltre a `compute_spese_per_categoria`/`compute_andamento_mensile`
  già esistenti.
- `StubLLMClient._decide_visualize` (rinominato da `_decide_chart`): cinque
  modalità — `saldo` (schede, nessun mese richiesto: è sempre "adesso"),
  `elenco` (tabella; tipo entrata/uscita **non filtrato di default** — "i
  movimenti di luglio" senza altro vuol dire tutti, non solo le uscite, a
  differenza dei grafici di riepilogo dove "spese" resta il default),
  `periodo` (barra, o barra impilata se "composizione/percentuale/quota"),
  `confronto` (barra raggruppata), `andamento` (linea). `OpenAILLMClient` ha
  già la function definition `visualize_tool` pronta per quando si
  generalizzerà con un LLM vero.
- `agent_brain._handle_visualize` (rinominato da `_handle_chart`): trova il
  database dell'organizzazione, calcola i dati veri, costruisce lo spec
  generico `{type, title, ...}` — la scelta della forma resta
  **deterministica**, non serve un LLM. Oltre 8 categorie, la coda si ripiega
  in "Altro" (limite della palette categorica validata, non arbitrario).
- Frontend ristrutturato: `Dashboard.jsx` possiede ora lo stato della "vista
  generata" e lo passa ad `AgentChat` (`onWidget`); la chat mostra solo una
  conferma testuale ("↑ Vista aggiornata nella pagina principale"), il
  rendering vero è in `components/widgets/WidgetCanvas.jsx` (sostituisce
  `ChartCard.jsx`, rimosso) — dispatcher su `type`: barra/barra
  raggruppata/barra impilata/linea (`recharts`, palette `dataviz`), tabella,
  schede (riusa `Card`).

**Verificato con i dati reali di Sampeyre**, ogni modalità via chat vera sulla
pagina reale (non solo l'API): saldo → schede (Banca 1.609€, Totale 1.609€);
composizione luglio → barra impilata (152+42=194€, coerente); elenco agosto →
tabella con le 2 righe corrette; confronto e andamento ri-verificati dopo il
refactor (stessi numeri esatti di prima). Corretto anche un bug trovato in
verifica: l'elenco filtrava le entrate di default, ora mostra tutto salvo
richiesta esplicita.

### Fase E — Rifiniture multi-tenant generiche
- ~~Multi-admin senza limiti, per qualsiasi settore~~ ✅ fatto, vedi sotto
- Backup automatico in cloud + export Excel/PDF
- Cattura scontrini via email dedicata

### Fase F — Test e avvio
- Prova con dati reali Sampeyre, correzioni, formazione, affiancamento

### Multi-admin (vero, non solo dichiarato) ✅ completato e verificato (16 agosto 2026)
Buco strutturale colmato: prima ogni login ERA un'azienda a sé (dati vuoti e
separati per ogni account), contro la decisione confermata nel piano
("nessun limite al numero di amministratori"). Refactor:

- Nuovo modello `Organization` (company_name, industry, invite_code):
  `User` ora ha `organization_id`, non più company_name/industry propri
  (restano come property proxy verso `organization`, per non rompere il resto
  del codice). `Integration` appartiene all'organizzazione, non al singolo
  utente — tutti gli amministratori la vedono.
- `POST /auth/register` ha due modalità: `company_name` (crea una nuova
  azienda, primo amministratore) oppure `invite_code` (si unisce a un'azienda
  esistente come amministratore aggiuntivo, stessi dati).
- Nuovo `api/team.py` + pagina `Team.jsx`: elenco amministratori dell'azienda,
  codice invito copiabile e rigenerabile.
- **Migrazione core**: dato che il cambio tocca lo schema di `users`/
  `integrations`, il database interno di Cortex (solo dati di test, non i dati
  finanziari di Sampeyre che vivono in `tenant_data/`, mai toccati) è stato
  azzerato e ricreato con una migrazione Alembic pulita.

**Verificato end-to-end, non solo dichiarato**: registrata una nuova azienda,
ricollegati i dati storici di Sampeyre già esistenti (stessi numeri di prima:
saldo 1.609€, risultato 859€, ecc. — nessun dato perso nel refactor),
registrato un **secondo** amministratore con il codice invito → vede
automaticamente stesso nome azienda, stesso settore, stessa integrazione,
stessi dati finanziari, senza inserire nulla. Verificato anche l'isolamento:
un'azienda estranea registrata senza invito non vede nulla di tutto questo.

### Viste salvate ("SavedView") ✅ completato e verificato (16 agosto 2026)
Generalizza `visualize_tool` (che conosce solo lo schema della finanza
no-profit) a qualunque settore, senza LLM: si configura **una volta** come
vedere una tabella collegata — a schede, a calendario, o a tabella con azioni
per riga — e la vista si ri-genera da sola ogni volta. Nato da tre esempi
concreti dell'utente: un immobiliare che vede i suoi annunci a schede, un
barbiere/tatuatore che vede gli appuntamenti a calendario, un'azienda che
aggiunge un bottone "Sollecito" su una tabella di debitori con email
personalizzata dai valori reali della riga.

- Nuovo modello `SavedView` (core db, migrazione additiva — nessun reset
  stavolta): organization_id, integration_id, table_name, mode
  (table/cards/calendar), column_mapping e row_actions (JSON).
- `api/views.py`: CRUD viste + `GET /views/{id}/data` (righe della tabella
  collegata formattate secondo la modalità, pronte per il frontend) +
  `POST /views/{id}/rows/{pk}/actions/{i}` — costruisce un'azione email
  personalizzata sostituendo `{{colonna}}` con i valori reali della riga, e
  riusa **lo stesso** meccanismo di conferma già collaudato in chat
  (`agent_state` + `POST /agent/confirm/{id}`), non un endpoint nuovo.
- `data_explorer.get_row`: nuova funzione per leggere una singola riga per
  chiave primaria.
- Frontend: nuova pagina `Viste.jsx` (form di configurazione + elenco viste
  renderizzate), `WidgetCanvas.jsx` esteso con `entity_cards` (schede
  generiche da colonne mappate), `calendar` (vista mensile con
  navigazione), e la tabella estesa con bottoni azione per riga + flusso di
  conferma. Nav item generico "Viste" per tutti i settori.

**Verificato con tre scenari reali, ciascuno con un database di prova
dedicato**: (1) tabella debitori → azione "Sollecito" → email realmente
recapitata a un server SMTP locale di test, con oggetto e testo
correttamente personalizzati dai valori della riga (nome, importo, scadenza)
— **non un mock**; (2) tabella annunci immobiliari → schede con titolo/
prezzo/stato mappati correttamente; (3) tabella appuntamenti → calendario
mensile con i 4 eventi nelle date giuste.

Un incidente in fase di verifica, risolto: ho trovato del testo offensivo in
un campo di una vista che non avevo scritto io. Prima di procedere ho
verificato i log del server SMTP (nessuna email offensiva era mai stata
inviata) e ho chiesto conferma all'utente prima di continuare — si trattava
di test dell'utente stesso nello stesso account, in parallelo alla mia
verifica (la stessa organizzazione ha ora 4 utenti: si è aggiunto anche
lui/lei come amministratore usando l'invito, prova pratica che il
multi-admin funziona davvero). Nessun dato è stato perso o compromesso.

Ripulito dopo la verifica: i tre database di prova (debitori/immobiliare/
barbiere) e il server SMTP locale sono stati rimossi. Le integrazioni
`custom_db` collegate a quei file e l'integrazione `gmail` di test
(puntata al server locale ormai fermo) restano nell'account e daranno
errore di connessione se riusate: da ricollegare o rimuovere quando si
riprende a testare.

### Viste salvate richiamabili dalla chat ✅ completato e verificato (16 agosto 2026)
Chiude il cerchio tra "Viste" (configurazione via form) e la chat: una volta
che una vista è salvata con un nome (es. "annunci"), scrivere *"mostrami gli
annunci"* la richiama nella pagina principale — stesso limite onesto già
applicato altrove (email, grafici): è un confronto testuale col nome che
l'utente stesso ha scelto, non vera comprensione del linguaggio su uno schema
mai visto. Quello resta legato a un LLM vero.

- `agent_brain._try_saved_view`: controllato *prima* dell'LLM/stub — cerca tra
  le Viste salvate dell'organizzazione un nome che compare nel messaggio,
  insieme a una parola come "mostrami"/"apri"/"vedi".
- Estratta la logica di formattazione (`view_rendering.py`) così
  `GET /views/{id}/data` e la chat producono esattamente la stessa resa da due
  punti d'ingresso diversi — nessuna duplicazione tra form e chat.
- `Dashboard.jsx`: le viste a tabella con azioni per riga funzionano anche
  quando richiamate dalla chat (stesso flusso di conferma email di Viste.jsx).

**Verificato con la vista reale creata in precedenza**: "mostrami gli
annunci" in chat sulla Dashboard → le stesse 3 schede immobiliari (titolo,
prezzo, stato) già viste configurando la vista dal form, ora comparse dalla
chat — dati reali, non un caso isolato.

**Aggiunta collaterale**: `pyodbc` (driver SQL Server) aggiunto alle
dipendenze e verificato importabile — utile per quando l'utente collegherà un
database Arca Evolution (SQL Server) in locale. Manca ancora il driver
Microsoft ODBC 18 per SQL Server (da installare quando ci sarà un db reale a
cui connettersi, per verificarlo con una connessione vera invece che a vuoto).

### Viste: mapping suggerito + anteprima live ✅ completato e verificato (16 agosto 2026)
Rispondeva all'osservazione dell'utente: il form di configurazione delle Viste
era potente ma poco intuitivo — troppi passaggi prima di capire cosa sarebbe
successo, si scopriva solo dopo aver salvato.

- **Mapping suggerito automaticamente**: quando si sceglie una tabella, i
  ruoli (titolo/sottotitolo/badge/data/colonna email) vengono proposti di
  default guardando il nome delle colonne (parole chiave tipo
  "nome"/"titolo", "prezzo"/"importo", "stato"/"tipo", "data"/"scadenza",
  "email"/"mail") — un punto di partenza sensato al posto di "—", sempre
  correggibile dai menu.
- **Anteprima live**: schede/calendario mostrano subito 5 righe reali della
  tabella con il mapping corrente, prima di salvare; le azioni email
  mostrano oggetto e testo già sostituiti con i valori veri della prima riga
  (stessa logica `{{colonna}}` del backend, solo per l'anteprima — l'invio
  vero resta sempre calcolato dal server).

**Verificato con dati reali**: sulla tabella "debitori" (Mario Rossi, importo
450, scadenza 2026-07-15), la colonna email è stata suggerita da sola
("email"), e l'anteprima ha mostrato correttamente *"Gentile Mario Rossi, le
ricordiamo un pagamento di 450 euro scaduto il 2026-07-15"* prima ancora di
salvare la vista.

**Corretto anche un bug visivo scoperto durante il lavoro**: in Integrazioni,
i valori mascherati lunghi (es. `connection_string`) sforavano fuori dalla
card fino a invadere il pannello accanto — mancava un limite di larghezza nel
flex-box. Ora troncano con ellissi e mostrano il valore intero al passaggio
del mouse.

### Connettore API generico + schede espandibili ✅ completato e verificato (16 agosto 2026)
Colma il buco: l'Hub Integrazioni e il Data Explorer sapevano parlare solo
con database. Ora un'azienda può collegare un'**API REST** (es. il portale
annunci di un immobiliare) esattamente come colleghereb un database — stessa
schermata Integrazioni, stessa schermata Viste, nessuna differenza per
l'utente.

- `services/api_connector.py` (nuovo): motore generico per sorgenti REST,
  parallelo a `data_explorer.py` — URL base, percorso elenco, percorso
  dentro la risposta JSON dove trovare l'array, campo identificativo, header
  di autenticazione opzionale.
- `services/data_source.py` (nuovo): fa da smistamento tra database
  (`data_explorer.py`) e API (`api_connector.py`) dietro un'unica interfaccia
  a 4 funzioni — Viste salvate, rendering e azioni di riga non sanno più
  quale delle due stanno usando.
- Provider `rest_api` (kind `data_api`) aggiunto al catalogo — appare nel
  form Integrazioni come qualunque altro provider.
- **Schede espandibili**: cliccando una scheda (modalità "cards" di una
  Vista) si apre un dettaglio con *tutti* i campi disponibili — per un
  database sono le stesse colonne già viste, per un'API può essere molto di
  più se è configurato un endpoint di dettaglio per singolo elemento (nuovo
  `GET /views/{id}/rows/{pk}`), esattamente il caso di un annuncio
  immobiliare: titolo/prezzo/stato nell'elenco, indirizzo/mq/locali/bagni/
  piano/classe energetica/agente/telefono ecc. nel dettaglio.

**Bug scoperto e corretto lungo il percorso**: nel form Integrazioni, tutti i
campi credenziali erano marcati "obbligatori" in HTML anche quando il
provider li definiva opzionali (es. header di autenticazione) — il bottone
"Salva" falliva silenziosamente senza dire perché. Aggiunto `required` per
campo nel catalogo provider invece che fisso per tutti.

**Verificato con un vero server HTTP locale** (non un mock): creata
un'integrazione `rest_api` puntata su un server Python reale con annunci
immobiliari fittizi ma realistici; vista "Annunci" a schede con mapping
suggerito automaticamente (titolo/prezzo/stato); espansione di una scheda
→ modal con tutti i 17 campi del dettaglio (indirizzo, mq, locali, bagni,
piano, anno costruzione, classe energetica, riscaldamento, spese
condominiali, descrizione, agente, telefono, data pubblicazione); richiamo
da chat "mostrami annunci" → stessa vista nella pagina principale.

## 4. Stato attuale e prossimo passo (16 agosto 2026)

Completate e verificate con dati/azioni reali: **Fase A**, **Fase B**, **Fase C**
(motore contabile + riconciliazione bancaria), **Fase D1** (agente reale,
esecuzione tool, invio email con conferma — a costo zero, LLM finto),
**multi-admin** (buco strutturale colmato), **viste salvate** (schede/
calendario/tabella con azioni, generico per qualunque settore, richiamabili
anche dalla chat, con mapping suggerito e anteprima live), **connettore API
generico** (database o REST indifferentemente, con schede espandibili a
tutti i campi disponibili), **segnalazioni proattive** (l'agente nota da
solo scadenze superate, soglie sforate, valori anomali — senza che l'utente
chieda).

### Segnalazioni proattive ✅ completato e verificato (16 agosto 2026)
Ultima delle tre aree che l'utente aveva indicato come "Cortex non ancora
abbastanza potente": oggi l'agente agiva solo su comando esplicito. Ora nota
da solo cose che meritano attenzione, con regole matematiche verificabili
(nessun LLM, gratuito) valutate al volo sui dati veri:

- **Modello `AlertRule`** (nuova tabella, migrazione additiva): una regola
  per organizzazione, su una tabella/risorsa collegata (database o API,
  stesso `data_source.py` delle Viste), con un tipo di condizione e un
  messaggio con `{{colonna}}` sostituibili (stesso motore di sostituzione
  delle azioni email delle Viste — estratto in `services/templating.py`
  condiviso tra i due).
- **`services/alert_engine.py`**: tre tipi di condizione, tenuti
  volutamente semplici perché restino gratuiti e verificabili — funzioni
  pure, non un modello statistico complesso:
  - *scadenza superata*: una colonna data nel passato oltre una tolleranza.
  - *soglia numerica*: una colonna supera (o è sotto) un valore fisso.
  - *valore anomalo*: una colonna si scosta dalla media (di tutte le righe o
    per gruppo) di più di N deviazioni standard — la "spesa anomala"
    dell'idea originale, senza servire un LLM.
- **Pagina Segnalazioni.jsx**: stesso pattern di suggerimento automatico
  delle Viste (una colonna data o numerica proposta guardando nome e tipo,
  correggibile), elenco delle regole configurate, elenco delle segnalazioni
  attive calcolate al momento (nessuno stato "letto/non letto" da gestire:
  ogni apertura riflette i dati veri in quel momento).
- **Pannello in Dashboard**: le prime segnalazioni compaiono nella pagina
  principale al caricamento, senza che l'utente chieda nulla in chat — il
  punto di partenza di tutta questa richiesta.

**Bug scoperto e corretto lungo il percorso**: il suggerimento automatico
della colonna numerica proponeva la chiave primaria (`id`, sempre un
intero, mai un valore su cui ha senso calcolare soglie o medie) — esclusa
dal suggerimento.

**Verificato con dati reali** sul database Sampeyre: regola "scadenza
superata" su `debitori` → 3 segnalazioni reali (Mario Rossi, Giulia Bianchi,
Luca Verdi, tutti scaduti rispetto a oggi); regola "soglia numerica" su
`movimenti.importo > 2000` → intercettato correttamente un movimento da
3.200€; regola "valore anomalo" sullo stesso importo (senza soglia fissa,
solo statistica) → stesso movimento da 3.200€ segnalato automaticamente
come fuori norma rispetto agli altri (perlopiù 40-900€). Le segnalazioni
comparse nel pannello Dashboard corrispondono esattamente.

### Nome per le integrazioni ✅ completato e verificato (16 agosto 2026)
Feedback diretto dell'utente: "i db non hanno un nome, è tutto poco
riconoscibile" — ogni integrazione appariva come "custom_db #3", "custom_db
#5"... impossibile distinguerle senza aprire ogni credenziale.

- Nuovo campo `name` su `Integration` (migrazione additiva, con backfill
  `"provider #id"` per le integrazioni già esistenti, così nessuna resta
  vuota).
- **Nome obbligatorio** alla creazione (Integrazioni), mostrato ovunque al
  posto di "provider #id": la card stessa, e i menu a tendina di Viste e
  Segnalazioni.
- **Rinomina in linea**: matita accanto al nome, nessuna pagina a parte.

Verificato rinominando dal vero form e controllando che il nuovo nome
comparisse subito nei menu di Viste e Segnalazioni.

### Export Excel/PDF ✅ completato e verificato (16 agosto 2026)
Il primo dei due pezzi mancanti individuati confrontando lo stato attuale col
documento originale di Sampeyre — l'export era la compensazione esplicita,
promessa lì, per aver perso il "programma desktop con dati in locale" a
favore del cloud (PLAN.md, Sezione 2).

- **`services/export_engine.py`**: `righe_a_excel()` generico (qualunque
  tabella, di qualunque settore, da database o API — usa
  `app.services.data_source` come tutto il resto) e `bilancio_a_pdf()`,
  specifico per il bilancio, l'unico report con un formato fisso da leggere
  così com'è, non solo righe.
- **Tre punti d'ingresso**: "Esporta Excel" su Dati (Data Explorer, qualunque
  tabella), su ogni Vista salvata (righe grezze della tabella collegata),
  ed "Esporta PDF" sul bilancio in Contabilità.
- **`scaricaFile()` condiviso** in `services/api.js`: un download protetto da
  login non può usare un semplice `<a href>` (il token va nell'header, non
  nell'URL) — passa da Axios con `responseType: "blob"` e simula il click su
  un link temporaneo, un solo posto invece di ripetere la logica ovunque.

**Corretta anche una piccola incoerenza trovata lungo il percorso**: in
Contabilità il selettore integrazione mostrava ancora "custom_db #1" invece
del nome (dimenticato nel fix precedente).

**Verificato scaricando davvero i file** (non solo controllando lo status
200): l'Excel delle categorie apre con `openpyxl` e contiene le 58 righe
reali; l'Excel di una Vista su API REST contiene i 3 annunci reali presi via
HTTP; il PDF del bilancio, riletto con un estrattore di testo, riporta
esattamente gli stessi numeri mostrati nella UI (entrate 3.700€, uscite
2.841€, risultato 859€, ecc.).

### Import Excel/CSV ✅ completato e verificato (16 agosto 2026)
Il secondo dei due pezzi mancanti individuati confrontando lo stato attuale
col documento originale di Sampeyre: come portare dentro lo storico dei 61
fogli Excel senza doverlo reinserire a mano riga per riga.

- **`services/import_engine.py`**: parsing di CSV (rilevamento automatico
  del separatore, tollerante al BOM di Excel) ed Excel (`.xlsx`/`.xlsm`),
  suggerimento del mapping colonna-file → colonna-tabella per corrispondenza
  esatta del nome normalizzato (stesso principio di "indovina" già usato per
  Viste e Segnalazioni), e validazione riga-per-riga: una riga con un valore
  sbagliato non blocca le altre, viene solo segnalata con il proprio numero
  e il motivo.
- **Flusso a due passaggi** in `Dati` (Data Explorer): prima un'anteprima
  (mapping suggerito, correggibile a mano, righe valide/errate — nulla
  scritto), poi una conferma esplicita che scrive davvero. Stesso principio
  di conferma prima dell'azione già usato per le email.
- Aggiunta `data_explorer.validate_row()`: convalida una riga contro lo
  schema della tabella senza scriverla — il "dry run" su cui si basa
  l'anteprima, riusa la stessa coercizione di tipo già scritta per l'update
  manuale delle righe.
- Solo per database (come la scrittura generica del Data Explorer): scrivere
  su un'API esterna arbitraria resta fuori scope.

**Verificato con un CSV reale** con intestazioni volutamente diverse dalle
colonne della tabella ("Nome Cliente" invece di "nome", "Importo" invece di
"importo_dovuto") e una riga con un valore non numerico apposta: il mapping
automatico ha preso solo le corrispondenze esatte (email, scadenza),
lasciando le altre due da assegnare a mano; una volta mappate, l'anteprima
ha segnalato correttamente "Riga 2: Valore non valido per 'importo_dovuto':
'non-numero'"; confermando l'import, le 2 righe buone sono state scritte
davvero nel database (verificate riapparire nella tabella con un nuovo id
autoincrementale) e quella malformata scartata senza toccare le altre.

### Prima connessione SQL Server reale (Arca) ✅ verificato (16 agosto 2026)
Non una funzionalità nuova ma la prima vera prova del Data Explorer generico
contro un database che non fosse SQLite: un container Docker con un vero
database Arca (gestionale, 380 tabelle) di un'azienda diversa da Sampeyre.

- Installato il driver Microsoft ODBC 18 per SQL Server (via Homebrew,
  rimandato apposta nella sessione precedente finché non c'era un database
  vero a cui connettersi) — `pyodbc.drivers()` ora lo vede.
- Creata una nuova azienda **"Trevalli"** (utente `peanogabriele70@gmail.com`)
  tramite il flusso di registrazione reale — stesso meccanismo di
  isolamento multi-tenant di Sampeyre, nessun trattamento speciale.
- Collegata l'integrazione (provider `sql_erp`, connection string
  `mssql+pyodbc://...`) e verificato che il Data Explorer generico legga le
  tabelle reali senza nessuna riga di codice specifica per SQL Server.

**Due bug generici scoperti e corretti**, entrambi invisibili finché il
motore era stato provato solo su SQLite:
1. **`ORDER BY` mancante**: SQLite/PostgreSQL accettano `LIMIT`/`OFFSET`
   senza `ORDER BY` (risultato non garantito ma non fallisce) — SQL Server
   lo *richiede* esplicitamente, senza fallisce con un errore SQL. Corretto
   ordinando sempre per chiave primaria (o la prima colonna, se assente).
2. **Colonne binarie non serializzabili**: SQL Server usa spesso una colonna
   `rowversion`/`timestamp` (qui `Ts`, per il controllo di concorrenza) che
   arriva come `bytes` — non convertibile in JSON, la risposta falliva con
   un 500 generico anche a query riuscita. Ora convertita in esadecimale.

Entrambi i fix sono nel motore generico (`data_explorer.py`), quindi
valgono per qualunque database, non solo Arca — beneficio collaterale reale
di aver collegato un database di produzione vero durante lo sviluppo.

**Verificato con dati reali**: tabella `CGMovT` (movimenti contabili) → 547
righe reali mostrate correttamente nella UI, comprese colonne binarie e
numeriche/decimali/data di ogni tipo. `AbiCab`, `CF` (65 anagrafiche),
`Ditta` lette correttamente allo stesso modo.

### Profilo contabile Arca ✅ completato e verificato (16 agosto 2026)
Richiesta dell'utente dopo aver collegato un vero database Arca (container
Docker, azienda "Trevalli"): non solo vedere un bilancio, ma avere **tutte
le funzioni di Sampeyre anche su ogni database Arca** — bilancio, IVA,
cespiti/ammortamenti. Costruito come secondo "profilo contabile"
(`services/accounting_engine_arca.py`), sullo stesso principio dei template
di `db_templates.py` ma per la lettura: un profilo per famiglia di schema,
riusabile da ogni database di quella famiglia senza configurazione, perché
lo schema Arca è standard tra installazioni diverse — collegare un secondo
database Arca funzionerà subito.

**Percorso reale, non lineare** — utile registrarlo perché ha prodotto le
scoperte più importanti:
1. Primo tentativo: leggere il bilancio già calcolato da Arca
   (`CGBilSaldoConto`). Scoperto che in questo database era **incompleto**
   (20 conti su 904 popolati per un intero esercizio) — numeri parziali
   spacciati per completi. Abbandonato.
2. Ricostruito il bilancio dai **movimenti contabili veri** (`CGMovR`,
   mappati alle voci ufficiali tramite `CGBilConto`) — stesso principio già
   usato per Sampeyre (sommare i movimenti, non fidarsi di uno snapshot).
3. Scoperto un mapping **deprecato**: `CGConto.Old_Cd_CGBil1` sembrava la
   mappatura giusta (nome generico, nessun avviso), ma il prefisso "Old_"
   svela che è superata da `CGBilConto` — trovato solo confrontando i
   conteggi di copertura (876/904 conti vs pochissimi).
4. Sommando tutti i movimenti dell'anno, ogni conto economico risultava
   **0,00€**: scoperte le scritture di **chiusura/apertura d'esercizio**
   (causali con `Tipo = 'F'`/`'E'`, standard di sistema Arca, non
   configurazione azienda-specifica) che azzerano i conti economici a fine
   anno — escluse dal Conto Economico (dove annullerebbero i movimenti
   reali), incluse nello Stato Patrimoniale (dove i saldi si accumulano nel
   tempo, non si azzerano).
5. Un bug di **case-sensitivity** («E.A.5.B_90» contro «E.A.5.b_90» — stesso
   codice, maiuscole diverse tra le due tabelle) faceva perdere silenziosamente
   un importo — risolto confrontando i codici senza distinguere maiuscole/minuscole.

**Verificato al centesimo**: il Conto Economico ricostruito coincide
esattamente con `UtilePerdita` (il risultato ufficiale già registrato in
Arca) per il 2019 e il 2020; per il 2018 (primo anno di utilizzo di Arca in
questo database) resta uno scarto isolato di 528€, verosimilmente una
rettifica manuale mai transitata come scrittura contabile — segnalato
esplicitamente in UI invece di nascosto, invece di fingere una precisione
che i dati non hanno.

**IVA e cespiti**, a differenza del bilancio, erano già dati pronti in Arca
(`CGLiqIva`: liquidazioni periodiche già calcolate; `CS`: anagrafica cespiti
con fondo cumulato reale) — letti e presentati così come sono, senza
ricostruzione. La quota annua di ammortamento è invece stimata dalla
percentuale configurata (costo × percentuale) perché in questo database i
movimenti di dettaglio (`CSMov`/`CSMovimento`) sono vuoti — dichiarato
esplicitamente, non spacciato per un valore registrato.

**"Contabilità" non è più specifica della finanza no-profit**: spostata tra
le voci di menu generiche (`industry_rules.py`), la pagina rileva da sola
quale dei due profili usare (`GET .../accounting/profilo`) e adatta
selettore (Anno+Mese per Sampeyre, Esercizio per Arca) e visualizzazione del
bilancio (tabella piatta per Sampeyre, albero gerarchico espandibile per
Arca) di conseguenza — verificato che Sampeyre continua a funzionare
identico a prima (nessuna riga toccata nel suo motore).

### Bilancio Arca provvisorio (senza chiusura ufficiale) ✅ verificato (16 agosto 2026)
Domanda dell'utente dopo aver visto solo 2018/2019/2020 disponibili:
"quindi del 2026 non c'è nulla, ma se ci fosse funzionerebbe?" — risposta
onesta: dipende. Il bilancio si basava solo su periodi che Arca ha
esplicitamente "chiuso" (`CGBilPeriodo`); un'azienda che scrive movimenti
tutto l'anno ma chiude il bilancio solo a fine anno (o su richiesta del
commercialista) si sarebbe trovata senza nulla da vedere per l'esercizio in
corso, pur avendo dati veri scritti in Prima Nota.

Corretto: se l'anno richiesto non ha un periodo ufficiale, `compute_bilancio`
ora ne costruisce uno **provvisorio** al volo — stessa tassonomia (struttura
voci) dell'ultimo periodo ufficiale disponibile, applicata ai movimenti reali
già registrati per quell'anno. Segnalato esplicitamente in UI (badge blu +
avviso), mai spacciato per un bilancio validato da Arca. L'IVA, allo stesso
modo, non dà più errore per un anno senza liquidazioni ancora presentate —
mostra semplicemente "nessuna liquidazione ancora", un dato onesto.

**Verificato**: 2026 (nessun movimento reale) → bilancio provvisorio,
tutte le voci a zero, badge visibile; IVA → messaggio pulito invece di un
errore; 2019/2020 (periodi ufficiali) → invariati, ancora esatti come prima.
Il selettore Esercizio nella UI include sempre l'anno corrente anche se non
tra i periodi ufficiali, etichettato "(provvisorio)".

### Cache di engine/schema: da 20 secondi a 20 millisecondi ✅ verificato (16 agosto 2026)
Feedback dell'utente dopo aver usato la Contabilità su Arca: "caricamento
dei dati troppo lungo ogni volta". Misurato prima di intervenire (disciplina
di questo progetto: numeri reali, non supposizioni) — il bilancio impiegava
**20,3 secondi**. Isolata la causa passo per passo: non le query (10ms),
ma la **reflection SQLAlchemy** (introspezione dello schema via ODBC) della
tabella `CGMovR` (108 colonne) — **16,3 secondi da sola** — rifatta
completamente da zero ad ogni singola richiesta HTTP, per ogni funzione,
perché ogni motore apriva un `create_engine()` nuovo e lo buttava via a
fine chiamata.

Corretto con `services/db_engine.py`: una cache condivisa (10 minuti di
TTL) di engine ed schemi riflessi, usata da tutti e tre i motori che
parlano con un database esterno (`data_explorer.py`, `accounting_engine.py`
di Sampeyre, `accounting_engine_arca.py`) — un solo posto, non tre copie.

**Verificato con numeri reali, prima/dopo**:
| Endpoint | Prima | Dopo (cacheato) |
|---|---|---|
| Bilancio | 20,3s | 0,065s (300×) |
| Ammortamenti | 2,5s | 0,023s (108×) |
| IVA | 0,35s | 0,017s (20×) |
| Righe tabella (Data Explorer) | 12,4s | 0,097s (128×) |

Il primo accesso a una tabella mai vista resta fisiologicamente più lento
(introspezione ODBC reale, non evitabile), ma solo quello — ogni chiamata
successiva sulla stessa tabella è quasi istantanea. Verificato anche che
Sampeyre continua a funzionare identico (saldi, viste salvate, stessi
numeri di prima).

Ancora da fare, nessuna bloccante sulle altre:
- **Backup automatico cloud**: rimandato, serve prima decidere un provider
  reale (Google Drive? S3?) — non ancora deciso con l'utente.
- **Profilo Arca**: saldi/budget/anomalie/riconciliazione bancaria non ancora
  costruiti per questo profilo (solo bilancio/IVA/ammortamenti, come richiesto
  in questo giro) — export PDF del bilancio Arca nemmeno (struttura
  gerarchica, serve un layout diverso da quello Sampeyre).
- **Feedback aperto dell'utente (16 agosto 2026)**:
  1. ✅ **fatto** — vista bilancio Arca semplificata: le voci a zero (la
     maggioranza, su un esercizio reale) sono nascoste di default, con un
     interruttore "Mostra anche le voci a zero" per chi vuole vedere tutto.
     Verificato: Conto Economico passato da 21 righe (quasi tutte a zero) a
     8 righe reali; Stato Patrimoniale Attivo (vuoto in questo esercizio
     demo) ora dice "Nessun saldo" invece di 25 righe a zero.
  2. ✅ **fatto** (17-18 agosto 2026) — saldi banca/cassa e comandi chat
     (grafici/tabelle a domanda), vedi le due sezioni dedicate sotto.
  3. creare Viste e Segnalazioni su un database con centinaia di tabelle dai
     nomi tecnici (Arca) è troppo difficile rispetto a farlo su Sampeyre
     (5 tabelle, nomi leggibili) — non ancora affrontato.

### Saldi banca/cassa per il profilo Arca ✅ verificato (17 agosto 2026)
Punto 2 del feedback dell'utente: Sampeyre mostra un riepilogo "Liquidità
attuale" (totale per ogni conto banca/cassa), Arca no. Aggiunto l'equivalente
generico: `CGConto.ContoBanca` (booleano) identifica i conti di liquidità in
qualunque database Arca — non un elenco di codici specifici a Trevalli.
`compute_saldi()` in `accounting_engine_arca.py` somma Dare-Avere da `CGMovR`
per ciascun conto flaggato (convenzione Attivo: Dare positivo, come per lo
Stato Patrimoniale). `GET /saldi` smista fra i due profili come già fa per
bilancio/IVA/ammortamenti; il frontend riusa lo stesso blocco React che già
disegnava la sezione per Sampeyre — nessun nuovo codice di rendering, solo
il fetch aggiuntivo.

Verificato end-to-end nel browser: la pagina Contabilità di Trevalli ora
mostra "Liquidità attuale" con i 4 conti reali di Arca La Valle (BANCA
POPOLARE DI MAROSTICA, CASSA DI RISPARMIO DI PADOVA E ROVIGO, BANCA POPOLARE
DI CASTELFRANCO VENETO, Cassa e monete nazionali) più il Totale — tutti a
0,00 €, dato onesto: in questo database dimostrativo incompleto non risultano
movimenti di prima nota sui conti bancari (verificato via SQL diretto, non è
un bug della query). Su un database Arca con prima nota bancaria completa la
stessa funzione produrrà cifre reali. Nessuna regressione su Sampeyre
(verificato via chiamata diretta: stesso risultato di prima, 1.609 € Banca).

### Comandi chat (grafici/tabelle a domanda) per il profilo Arca ✅ verificato (18 agosto 2026)
Seconda metà del punto 2 del feedback: su Sampeyre la chat riconosce frasi
come "quanto abbiamo in banca?", "mostrami le spese di luglio", "confronta
le spese di luglio con maggio", "andamento delle entrate nel 2026",
"elenco dei movimenti di agosto" e genera al volo un grafico/tabella/scheda
nella Dashboard (agent_brain.py `_handle_visualize` + llm_client.py
`StubLLMClient._decide_visualize`, riconoscimento a pattern, non un vero
LLM). Su Arca, collegata allo stesso database, la chat rispondeva sempre
"non ho capito" — nessuno di questi comandi era cablato sul motore Arca.

Il riconoscimento del comando (quale grafico, quale mese, quale verso
entrata/uscita) è generico e già funzionava identico per entrambi i
profili — mancava solo l'esecuzione lato Arca. Aggiunte in
`accounting_engine_arca.py` le tre funzioni equivalenti a quelle di
Sampeyre (`compute_spese_per_categoria`, `list_movimenti`,
`compute_andamento_mensile`), e `agent_brain.py` ora sceglie il motore
giusto con lo stesso rilevamento automatico già usato da `api/accounting.py`
(`_motore_contabile`, basato su `is_arca_schema`) — il resto del codice
(grafici, tabelle, schede) è rimasto identico, non sapeva né sa quale dei
due motori ha chiamato.

La difficoltà specifica di Arca: non esiste una tabella "categorie"
configurata dall'azienda come in Sampeyre. La "categoria" più vicina che
Arca offre già è la voce di Conto Economico (`CGBil`, Sezione 'E') a cui il
conto movimentato è mappato tramite `CGBilConto` — la stessa classificazione
già costruita e verificata per il bilancio (stessa tassonomia, stessa
esclusione delle scritture di apertura/chiusura, stesso segno Avere-Dare).
Un movimento su un conto puramente patrimoniale (es. "CLIENTI", "IVA
VENDITE", un pagamento fornitore) non ha un verso entrata/uscita e viene
escluso dai grafici per categoria — mostrato comunque nell'elenco
movimenti (etichettato "Patrimoniale") quando non è richiesto un filtro
per tipo.

**Verificato end-to-end con dati reali** (Trevalli/Arca La Valle, gennaio
2020, mese con 50 movimenti reali):
- "quanto abbiamo in banca?" → le stesse card di liquidità del punto sopra.
- "mostrami le spese di gennaio 2020" → grafico a barre reale (Altri oneri
  di gestione 284,67€, Spese telefoniche 141,76€, Consulenze 23,77€, Altri
  21,96€) — **verificato visivamente nel browser**, renderizzato nella
  Dashboard esattamente come per Sampeyre.
- "elenco dei movimenti di gennaio 2020" → tabella di 50 righe con conto,
  descrizione, categoria e importo con segno corretto.
- "confrontami le spese di gennaio 2020 con dicembre 2020" → grafico a
  barre affiancate su 5 categorie.
- "andamento delle entrate nel 2020" → stesso limite già presente e
  identico su Sampeyre: senza un nome di mese nella frase il riconoscitore
  a pattern non estrae l'anno e usa quello corrente (nessuna regressione,
  verificato riproducendo lo stesso comportamento anche su Sampeyre con la
  stessa frase — limite del riconoscitore a pattern, non specifico di Arca,
  non affrontato in questo giro).

Nessuna regressione su Sampeyre (stesso comando "quanto abbiamo in banca?"
→ stesso risultato di sempre, 1.609 € Banca).

### "Caricamenti ancora infiniti" — timeout Axios + indicatori mancanti ✅ verificato (18 agosto 2026)
Segnalato di nuovo dall'utente dopo il fix di performance del 16 agosto
("caricamenti ancora infiniti" su Contabilità e Dati). Misurato di nuovo con
numeri reali (non supposizioni): tutti gli endpoint coinvolti rispondevano
in 0,05–0,14s, e aprendo `CGMovR` (108 colonne, 2.609 righe — la tabella che
causava i 20 secondi originali) nella pagina Dati il caricamento era
istantaneo. Il fix del 16 agosto teneva.

Trovate però due cause concrete, non ipotetiche, di un "infinito" vero (non
solo percepito):
1. **Nessun timeout su Axios** (`services/api.js"): il default è 0, cioè
   attesa infinita. Se una richiesta si blocca davvero — connessione al
   database esterno caduta a metà, pool di connessioni SQL Server esaurito,
   backend riavviato a metà richiesta (capita spesso in sviluppo con
   `--reload` attivo) — il frontend restava appeso per sempre senza errore.
   Aggiunto un timeout di 45 secondi (abbondante sopra il caso più lento mai
   misurato, ma limitato): oltre quella soglia ora arriva un errore
   leggibile invece di un'attesa eterna.
2. **Nessun indicatore di caricamento per i dati contabili** (Contabilità,
   Passo 3) né per il cambio tabella (Dati): se una di quelle richieste era
   anche solo lenta (non bloccata — es. la prima volta che si legge una
   tabella dopo che la cache di `db_engine.py` è scaduta, o dopo un riavvio
   del backend che la svuota), la pagina restava muta, senza nessun
   cambiamento visibile — indistinguibile per l'utente da un vero
   "caricamento infinito" anche quando in realtà sarebbe arrivato tra
   qualche secondo. Aggiunto "Caricamento dati contabili..." /
   "Caricamento tabella..." per rendere visibile l'attesa reale invece di
   lasciare la pagina vuota.

Verificato nel browser con refresh forzato (Cmd+Shift+R) dopo il fix:
Contabilità e Dati tornano a caricare normalmente — confermato dall'utente
("risolto, ora carica"). La causa di quell'episodio specifico era comunque
un bundle JS in cache/HMR non aggiornato (non i due problemi sopra), ma i
due problemi sopra restavano comunque reali e ora sono corretti.

### Modelli pronti (Viste senza configuratore) per il profilo Arca ✅ verificato (18 agosto 2026)
Ultimo punto aperto del feedback originale dell'utente: configurare una
Vista scegliendo a mano tabella e colonne tra le 380 di un database Arca è
troppo difficile rispetto a farlo su Sampeyre (5 tabelle, nomi leggibili).
Le Viste salvate (`SavedView`) restano comunque legate a una singola
tabella per costruzione (`view_rendering.py` legge una tabella e mappa le
colonne) — non il posto giusto per un report aggregato su più tabelle come
"chi mi deve pagare". Aggiunto invece un meccanismo parallelo, più vicino ai
widget della chat che alla Vista configurabile: **modelli pronti**, calcolati
al volo (non salvati) da funzioni server-side che già sanno quali tabelle
Arca usare — stesso principio già applicato a bilancio/IVA/saldi.

Due modelli aggiunti in `accounting_engine_arca.py`
(`compute_clienti_scoperti`, `compute_fornitori_da_pagare`, appoggiati su
`_saldi_anagrafiche`): saldo aperto per cliente/fornitore, sommando
Dare-Avere di tutti i movimenti mai registrati sulla sua partita
(`CGMovR.Cd_CF`, filtrati sui nominativi `CF.Cliente`/`CF.Fornitore`) —
stessa convenzione Attivo/Passivo già usata per lo Stato Patrimoniale e per
`compute_saldi`. Due endpoint nuovi (`GET .../modelli/clienti-scoperti`,
`GET .../modelli/fornitori-da-pagare`, solo profilo Arca — 400 esplicito
altrimenti) restituiscono direttamente uno spec "table" già pronto per
`WidgetCanvas`, zero codice di rendering nuovo nel frontend. In `Viste.jsx`,
una sezione "Modelli pronti" (visibile solo se l'integrazione selezionata è
profilo Arca) con due bottoni: un click, nessuna tabella/colonna da
scegliere, risultato subito.

**Verificato end-to-end nel browser** con dati reali di Trevalli: "Fornitori
da pagare" mostra "SCRITTURE DI ASSESTAMENTO — 4.608,00 €" — lo stesso
identico numero già presente nello Stato Patrimoniale Passivo del bilancio
("Debiti verso fornitori"), un incrocio che conferma la correttezza del
calcolo con un dato indipendente. "Clienti con saldo scoperto" mostra
correttamente una lista vuota (nessun cliente con saldo aperto in questo
database dimostrativo — coerente con l'assenza di movimenti sui conti banca
già osservata, non un bug). Verificato anche il fallback: un'integrazione
non-Arca mostra "Nessun modello pronto per questa integrazione — usa il
configuratore qui sotto" invece dei bottoni, e l'endpoint risponde 400 con
messaggio chiaro se chiamato direttamente su un'integrazione Sampeyre.

Con questo sono chiusi tutti e quattro i punti del feedback del 16 agosto
2026 (vista bilancio troppo complicata, funzioni mancanti rispetto a
Sampeyre, Viste/Segnalazioni difficili da creare, caricamento lento).

### Cortex agisce da solo: controllo automatico + riepilogo mattutino ✅ verificato (18 agosto 2026)
Feedback dell'utente: "non è abbastanza, Cortex di per sé non fa nulla".
Vero: anche le "Segnalazioni proattive" (Fase precedente), nonostante il
nome, scattavano solo quando l'utente apriva la pagina — nessun controllo
periodico, nessuna notifica, nessuna azione presa da sola. Confermato con
l'utente cosa costruire (non un'ipotesi): controllo automatico delle
Segnalazioni ogni 30 minuti con notifica email, più un riepilogo mattutino
automatico. Un assistente IA vero (LLM reale a pagamento) resta rimandato,
come già deciso l'11-12 agosto.

**Architettura**: `services/scheduler.py` — un loop asyncio avviato una sola
volta all'avvio del server (`main.py`, `lifespan`), vive per tutta la vita
del processo, nessuna dipendenza nuova (né cron esterno né APScheduler).
`services/notifiche.py` — la logica vera, richiamabile anche fuori dal loop
(usato per la verifica):
- `controlla_segnalazioni`: valuta le regole già attive di ogni azienda
  (stesso `alert_engine` già esistente) e manda un'email per ogni
  segnalazione **nuova**. Deduplicazione tramite la nuova tabella
  `NotificaInviata` (chiave `segnalazione:{regola_id}:{pk}`): una condizione
  che resta vera nel tempo (es. una scadenza non ancora saldata) genera
  un'email solo alla prima comparsa, non una ogni 30 minuti.
- `invia_riepilogo_mattutino`: al massimo un'email al giorno per azienda
  (chiave `riepilogo:{data}`), dopo le 8 del mattino, con la liquidità
  attuale (`compute_saldi`, generico Sampeyre/Arca).
- Entrambe riusano l'integrazione Gmail/SMTP che l'azienda ha già collegato
  per l'invio manuale (`agent_brain`/`api/agent.py`) — **nessuna
  configurazione nuova**: un'azienda che non ha ancora Gmail semplicemente
  non riceve notifiche (non un errore), e riparte da sola quando la collega.
  Una notifica è segnata "inviata" solo se l'invio è davvero riuscito: un
  SMTP momentaneamente irraggiungibile fa ritentare al ciclo successivo
  invece di perdere quella notifica per sempre.

**Verificato con un invio reale**, non un mock: creata una vera regola
"Debitori scaduti" su Sampeyre (scadenza superata, tabella `debitori`, 3
debitori realmente scaduti di 34/49/17 giorni), avviato un vero server SMTP
locale (`aiosmtpd`, sostituisce Gmail per il test) sulla stessa porta già
configurata nell'integrazione Gmail di test di Sampeyre. Risultato:
- Il **server reale** (non uno script di verifica separato) ha fatto
  scattare da solo il riepilogo mattutino al riavvio di uvicorn dopo la
  modifica di `main.py` — senza che io lo chiedessi, la prova diretta che
  "Cortex fa qualcosa da solo" ora è vera.
- Il ciclo manuale successivo ha inviato le 3 email di segnalazione (una per
  debitore, contenuto reale e corretto — nomi, importi, giorni di ritardo
  tutti esatti) e correttamente NON ha rimandato il riepilogo (già inviato
  nel ciclo precedente).
- Un terzo ciclo di controllo ha restituito `(0, 0)`: nessun doppio invio
  per una condizione ancora vera — la deduplicazione funziona, verificato
  anche attraverso un riavvio reale del processo (la tabella
  `NotificaInviata` è su disco, sopravvive al restart).

Non ancora fatto: nessuna UI per vedere lo storico delle notifiche inviate
(la richiesta era "che Cortex faccia qualcosa da solo", non necessariamente
vederlo in una pagina — l'email stessa è la prova). Il server SMTP di test
usato per la verifica non è parte del prodotto, va sostituito con Gmail vero
quando Sampeyre/Trevalli collegano la loro casella reale.

### Spiegazioni automatiche degli scostamenti ✅ verificato (18 agosto 2026)
Richiesta dell'utente dopo le notifiche automatiche: "serve altro di
innovativo" — le notifiche da sole restavano un altro modo di mostrare gli
stessi numeri. Proposte tre direzioni concrete (previsione di cassa,
scadenzario fiscale automatico, spiegazioni automatiche degli scostamenti);
l'utente ha scelto quest'ultima.

`services/narrazione.py` (nuovo): confronta un periodo con quello
immediatamente precedente usando `compute_spese_per_categoria` (già
esistente su entrambi i profili) e scrive in italiano leggibile non solo
*quanto* è cambiato ma *perché* — quali voci hanno inciso di più, comprese
voci comparse o sparite da un mese all'altro. Nessun LLM: regole + template
scritti a mano sui dati già calcolati, stesso principio "gratuito e
verificabile" di `alert_engine.py`. Generico per costruzione: la funzione
non sa se sta leggendo Sampeyre o Arca, riceve il motore giusto dal
chiamante (stesso pattern di `agent_brain._handle_visualize`).

Tre punti d'accesso allo stesso risultato:
- `GET /accounting/spiegazione` (anno/mese/tipo opzionali, default mese
  corrente).
- Comando chat: "perché sono aumentate le spese?", "spiegami le spese di
  luglio", "cosa è cambiato" — nuovo modo "spiegazione" in
  `llm_client.py`/`agent_brain.py`, nuovo tipo di widget "narrative" in
  `WidgetCanvas.jsx` (un paragrafo di testo, non un grafico).
- Sezione "Cosa è cambiato" in Contabilità, sempre sul mese corrente
  (indipendente dall'esercizio di bilancio scelto altrove nella pagina —
  è una domanda diversa, "come sto andando adesso").

**Verificato con dati reali su entrambi i profili**: Sampeyre — "le spese di
Agosto 2026 sono aumentate di 750,00 € (387%) rispetto a Luglio 2026 (...) il
motivo principale: 'Energia elettrica' è aumentata di 748,00 €"; Arca/Trevalli
— "le spese di Luglio 2020 sono diminuite di 953,53 € (95%) (...) non ci
sono più movimenti in '- Servizi per acquisti'; ed è comparsa la voce
'- Spese telefoniche'". Verificato anche il caso "nessun cambiamento" (Arca,
Agosto 2026, nessun dato: "sono rimaste stabili... 0,00 €", non un errore).
Verificato visivamente nel browser sia il rendering in chat (Dashboard) sia
la sezione dedicata in Contabilità.

### Dashboard reale al posto delle statistiche finte ✅ verificato (20 agosto 2026)
Feedback dell'utente: "è davvero troppo incasinato e alla fine risulta
quasi inutile". Diagnosi concreta (non un'impressione): la Dashboard, la
prima pagina che si apre, mostrava due card "Overview"/"Recent Activity"
cablate a **zero fisso**, con un commento nel codice stesso mai risolto
("in produzione questi valori arriverebbero da servizi reali") — risalente
alla Fase A del progetto, mai aggiornato dopo che il motore contabile e le
spiegazioni automatiche sono arrivati. La prima cosa che un utente vedeva
aprendo Cortex era, di fatto, vuota.

Corretto riusando solo funzioni già costruite e verificate altrove
(`compute_saldi`, `narrazione.spiega_scostamento`): `api/dashboard.py` ora,
quando l'azienda ha un database contabile collegato riconosciuto (Sampeyre
o Arca, stesso rilevamento automatico di tutto il resto), calcola un vero
riepilogo — liquidità attuale + "cosa è cambiato" questo mese — al posto
delle statistiche segnaposto. Un'azienda senza schema contabile riconosciuto
vede ancora le card generiche per settore (invariate, nessuna regressione).

Approfittato per eliminare una duplicazione già notata: la stessa funzione
"trova la prima integrazione database dell'azienda" esisteva identica in tre
punti (`agent_brain.py`, `services/notifiche.py`, e ora anche qui) —
centralizzata in `integration_providers.find_first_database_integration`,
gli altri due ora la richiamano invece di reimplementarla.

**Verificato con dati reali**: Trevalli/Arca mostra i 4 conti banca (0,00 €,
dato onesto) + "Le spese di Agosto 2026 sono rimaste stabili..."; Sampeyre
mostra Banca 1.609 € + la stessa spiegazione già verificata prima ("Energia
elettrica aumentata di 748€..."). Confermato nel browser: non più
"Overview 0 / Recent Activity 0", nessun errore in console.

Ancora da fare (prossimo passo concordato con l'utente): la pagina
Contabilità resta un'unica lunga scrollata (saldi, cosa è cambiato,
bilancio, IVA, ammortamenti tutti impilati) — da riorganizzare in sezioni.

**Correzione immediata (20 agosto 2026)**: l'utente ha notato che su
Trevalli "rimangono tutti 0" anche dopo questo fix. Causa reale, non lo
stesso problema: "Cosa è cambiato" confrontava sempre il mese di calendario
corrente (agosto 2026), ma l'ultima registrazione reale nel database Arca
di Trevalli è dicembre 2020 — confrontava due mesi vuoti. Aggiunta
`ultimo_periodo_con_movimenti` a entrambi i motori (MAX della data sui
movimenti, non l'intera tabella caricata in memoria — su Arca una query
`func.max` su CGMovR, non `_fetch_all`) e
`narrazione.spiega_ultimo_periodo_con_dati`: la Dashboard ora parte
dall'ultima attività contabile reale, non dal calendario. Un comando
esplicito in chat ("le spese di questo mese") continua a usare il mese
vero — lì l'utente ha chiesto proprio quello, diverso dal riepilogo
automatico. Verificato: Trevalli ora mostra "Dicembre 2020: le spese sono
aumentate di 3.327,68€ (...)" con voci reali, invece di "stabili, 0€".
Aggiunta anche una nota esplicita sotto le card quando la liquidità è
davvero a zero ("nessun movimento risulta mai registrato..."), per non
lasciare lo stesso dubbio ("perché è a zero?") anche quando lo zero è un
dato vero e non un bug.

### Contabilità a schede invece di un'unica scrollata ✅ verificato (20 agosto 2026)
Secondo problema dello stesso feedback: Bilancio, IVA, Ammortamenti (e per
Sampeyre anche Budget, Anomalie, Riconciliazione bancaria) erano tutti
impilati e sempre visibili insieme in un'unica pagina lunghissima. Nessun
cambiamento ai dati o alla logica di caricamento (stesse `useEffect`,
stesse chiamate API, nessun rischio di regressione sui dati) — solo a cosa
è condizionato il *rendering*: ogni sezione ora è dietro `tabAttiva ===
"<scheda>"`, con una barra di schede sopra (Bilancio / IVA / Ammortamenti,
più Budget / Anomalie / Riconciliazione bancaria solo per il profilo
Sampeyre, che le calcola). "Liquidità attuale" e "Cosa è cambiato" restano
invece sempre visibili sopra le schede: sono l'unico riepilogo rapido di
tutta la pagina, nasconderli dietro un click li avrebbe resi meno utili,
non più ordinati.

Verificato nel browser: switch tra le tre schede di Arca (Bilancio → IVA →
Ammortamenti) — ogni click sostituisce completamente il contenuto
precedente, non lo affianca; nessun errore in console. La scheda attiva si
resetta a "Bilancio" ad ogni cambio di integrazione o profilo (coerente:
un'azienda diversa non deve ritrovarsi su "Anomalie" se quel profilo non
ce l'ha).

Con questo sono affrontati entrambi i punti del feedback "troppo
incasinato e alla fine risulta quasi inutile" del 20 agosto 2026.

### Un login per più aziende clienti (Membership + Portfolio) ✅ verificato (25 agosto 2026)
Domanda dell'utente: "non è un prodotto vendibile alle aziende, a cosa
dovrebbe servire?" — a valle della discussione: il cliente non è un solo
tipo di azienda, è un parco clienti eterogeneo (alcuni con un gestionale
vero come Trevalli/Arca, altri senza nulla come Sampeyre), e serve sia
"versatile per entrambi i casi" sia "un login solo per seguirli tutti"
invece di un account separato per ogni azienda cliente — oggi impossibile:
`User.organization_id` era un vincolo rigido uno-a-uno.

**Cambio strutturale** (il più grande di questa sessione, per questo
confermato con l'utente prima di partire): nuova tabella `Membership`
(user_id, organization_id) — un utente può averne più di una.
`User.organization_id` resta, ma cambia significato: non più "l'unica
azienda dell'utente", ma "quale delle sue aziende sta guardando adesso" —
scelta pensata apposta per non dover toccare nessuno degli endpoint
esistenti (tutti leggono già `current_user.organization_id`, che continua a
funzionare identico). Il JWT codifica solo l'utente, mai l'azienda: cambiare
azienda attiva è una scrittura sul database, non un nuovo token.

Nuovi endpoint in `api/auth.py`:
- `GET /auth/my-organizations` — elenco delle aziende accessibili.
- `POST /auth/switch-organization` — cambia l'azienda attiva tra quelle già
  accessibili (verificato che l'utente abbia una Membership, altrimenti 403
  — non deve bastare indovinare un id per entrare nei dati di un'altra
  azienda).
- `POST /auth/join-organization` — si unisce a un'azienda esistente col suo
  codice invito (lo stesso già usato in fase di registrazione, ora
  utilizzabile anche da loggati) e la rende attiva.
- `POST /auth/create-organization` — crea un nuovo cliente da zero restando
  collegati con lo stesso account (il caso comune di chi imposta Cortex per
  ogni nuovo cliente).

**Portfolio** (`GET /dashboard/portfolio`, pagina "I miei clienti" in
Sidebar): un riepilogo di tutte le aziende accessibili in un colpo d'occhio
— liquidità, "cosa è cambiato", numero di segnalazioni aperte — senza dover
cambiare azienda attiva solo per guardare. Nessun calcolo nuovo: riusa
`_riepilogo_finanziario` (già scritta per la Dashboard singola, già
parametrizzata per organization_id) e una nuova
`alert_engine.valuta_tutte_le_regole` estratta dal codice già esistente di
`GET /alerts/segnalazioni` (che ora la richiama anche lei, invece di
duplicare la stessa logica una terza volta).

**Verificato end-to-end con dati reali**, non solo per organization_id
fisso: l'utente di Trevalli si è unito a Sampeyre con il suo vero codice
invito (`POST /auth/join-organization`), il Portfolio ha mostrato
correttamente entrambe le aziende con i loro dati veri (Sampeyre: 1.609€,
4 segnalazioni aperte sui debitori scaduti; Trevalli: 0€, dicembre 2020) —
poi lo switch da Sampeyre a Trevalli tramite il bottone "Vai a questa
azienda" ha aggiornato correttamente la Dashboard con i dati della nuova
azienda attiva. Verificata anche la creazione di un nuovo cliente da zero
(azienda "Cliente Demo Verifica", mostrata subito come attiva con "nessun
database contabile collegato ancora" — stato onesto per un'azienda nuova),
poi ripulita. Nessun errore in console in nessun passaggio.

Non ancora fatto: la pagina Team (amministratori di un'azienda) resta
scoperta solo sugli utenti la cui azienda "di origine" coincide — un
consulente aggiunto via Membership non compare nell'elenco Team di
quell'azienda cliente. Non affrontato in questo giro, da vedere se serve.

### Azioni pronte, non solo notifiche ✅ verificato (25 agosto 2026)
Domanda dell'utente, la più diretta finora: "a cosa dovrebbe servire" — e
dopo aver risposto "controlla Arca al posto tuo e te lo spiega": "non
basta, serve qualcosa di più concreto ... es. prepara da sola il sollecito
a un fornitore/cliente scaduto". Giusto: un'email di notifica ogni tanto
non è un motivo per pagare un abbonamento, un'azione vera fatta al posto
tuo lo è.

Estesa la stessa infrastruttura di sicurezza già in uso per le email
dell'agente in chat (bozza preparata, mai inviata senza conferma esplicita)
alle Segnalazioni automatiche. Una regola (AlertRule) può ora avere un
`azione_template` opzionale collegato ({to_colonna, oggetto_template,
corpo_template} — stessa sintassi `{{colonna}}` già usata ovunque nel
sistema, via `services/templating.py`): quando la regola scatta per una
riga NUOVA, il ciclo automatico (`services/notifiche.py`, ogni 30 minuti)
non manda solo la notifica interna all'azienda — prepara anche una bozza
pronta con i dati veri di quella riga (`models.AzionePendente`, tabella
persistita, non in memoria: deve restare visibile a qualunque
amministratore anche ore dopo, anche dopo un riavvio del server, non solo
a chi era loggato quando è stata generata — nel caso comune nessuno lo
era, l'ha fatto Cortex da solo).

Nuova pagina/sezione "Azioni pronte da confermare" (Segnalazioni.jsx):
elenco delle bozze in attesa con destinatario/oggetto/testo completi,
"Conferma e invia" (manda davvero, tramite l'integrazione Gmail/SMTP già
collegata dall'azienda) o "Scarta". L'invio resta sempre una scelta umana,
mai automatico — stesso principio di sicurezza di tutto il resto del
sistema, solo il *lavoro di preparazione* è automatico.

Refactoring minore per riuso: `alert_engine.valuta_regola_con_riga`
(nuova) espone anche la riga intera, non solo un messaggio già formattato
per un umano — `valuta_regola` (pubblica, usata da GET /alerts/segnalazioni)
ora si appoggia su questa togliendo "riga", nessuna duplicazione della
logica di valutazione.

**Verificato end-to-end con un invio reale, dalla UI vera**: aggiunto un
`azione_template` alla regola "Debitori scaduti" già esistente su
Sampeyre (destinatario = colonna email, testo di sollecito con
{{nome}}/{{importo_dovuto}}). Il ciclo automatico ha preparato 4 bozze
reali (una per debitore scaduto). Dalla pagina Segnalazioni nel browser,
click su "Conferma e invia" per Sara Blu → email reale arrivata
all'indirizzo del *debitore* (sara.blu@example.com), non a Sampeyre
stessa — contenuto verificato byte per byte nel server SMTP di test.
Contatore sceso da 2 a 1 senza refresh manuale, nessun errore in console.
Verificato anche "Scarta" via API (stato → rifiutata, non ripreparata al
giro successivo).

### LLM reale (Gemini) collegato ✅ verificato, con un limite pratico importante (25 agosto 2026)
L'utente ha fornito una vera chiave API Gemini (Google AI Studio) e chiesto
di collegarla per un assistente IA vero — la decisione "rimandiamo per ora"
dell'11-12 agosto è stata rivista ora che il costo non è più un ostacolo
(livello gratuito). Le variabili incollate dall'utente (`NEXT_PUBLIC_GEMINI_API_KEY`,
riferimenti a "Route Handler"/"Capacitor") erano chiaramente di un altro
progetto (Next.js/Capacitor, non Cortex) — segnalato all'utente; usata solo
`GEMINI_API_KEY` lato server (mai esposta al frontend, stessa architettura
già in uso per OPENAI_API_KEY: le chiamate all'LLM avvengono sempre nel
backend, mai dal browser).

**Costruito**: `GeminiLLMClient` in `services/llm_client.py`, stessa
interfaccia di `OpenAILLMClient` (mai stata testata prima con una chiave
vera) e stessi due tool (`email_tool`, `visualize_tool`) — estratti in
`_function_declarations()` condivisa tra i due invece di due copie dello
schema che rischiavano di disallinearsi (successo davvero: "spiegazione"
era stato aggiunto al riconoscimento a pattern ma non allo schema per un
LLM vero — corretto nello stesso passaggio). `get_llm_client()` ora sceglie
Gemini se `GEMINI_API_KEY` è impostata, altrimenti OpenAI, altrimenti lo
Stub gratuito — un cambio di `.env`, non di codice, per l'intera
piattaforma (non per singola azienda: `OPENAI_API_KEY`/`GEMINI_API_KEY`
restano "default di piattaforma", come già commentato in `config.py`).

**Tre bug reali trovati provando chiamate vere** (non ipotetici — uno di
questi ha prodotto un errore 500 reale in fase di verifica):
1. Il modello di default scritto nel codice (`gemini-2.0-flash`) non esiste
   più — l'errore vero dell'API indicava il modello attuale
   (`gemini-3.6-flash`), usato per aggiornare il default.
2. Gemini restituisce SEMPRE i numeri come float (2026.0, non 2026: il tipo
   Struct di protobuf usato per gli argomenti di una function-call non
   distingue interi da decimali) — un `date(2026.0, 7.0, 1)` più a valle
   sarebbe esploso. Corretto con `_proto_a_python()`, conversione ricorsiva
   esplicita (float intero → int) invece di un dict()/list() superficiale.
3. Un LLM vero può legittimamente omettere `periodi`/`anno` quando l'utente
   non specifica un mese/anno esplicito (lo schema li rende opzionali, solo
   "modo" è obbligatorio) — mentre StubLLMClient li passa sempre. Tre punti
   in `agent_brain.py` (`elenco`, `periodo`, `spiegazione`, più `andamento`
   per "anno") facevano `args["periodi"][0]` senza controllo, sollevando un
   KeyError non gestito (500 reale, riprodotto con
   "come sono andate le entrate quest'estate rispetto a prima?"). Corretto
   con `_periodo_richiesto()` (nuova, ripiego al mese corrente) e lo stesso
   ripiego per "anno" in modalità andamento.

Aggiunta anche resilienza non richiesta esplicitamente ma necessaria:
`AgentBrain._decidi_con_ripiego` ora prova il client configurato e, se
fallisce per qualunque motivo (rete, chiave non valida, quota esaurita),
degrada silenziosamente allo StubLLMClient gratuito invece di rompere la
chat con un errore 500 — un provider a pagamento che smette di funzionare
non deve rendere Cortex inutilizzabile.

**Verificato con chiamate reali, non simulate** — inclusi casi che
StubLLMClient non avrebbe mai riconosciuto (prova diretta del valore
aggiunto): "dimmi come mai le spese sono schizzate in alto questo mese" →
`modo=spiegazione` corretto; "quali sono le nostre spese principali questo
mese?" → grafico di composizione corretto, verificato anche nel browser
reale; email scritta in linguaggio naturale ("manda una mail... dicendo che
il pagamento risulta ancora in sospeso") → bozza con oggetto/corpo
professionali generati dal modello, sempre con conferma esplicita richiesta
prima dell'invio (stesso meccanismo di sicurezza di sempre, invariato).

**Limite pratico importante, scoperto verificando e non ipotizzato**: il
livello gratuito di Gemini per `gemini-3.6-flash` permette solo **20
richieste al giorno per modello** (quota esaurita durante questa stessa
sessione di verifica, errore reale
`ResourceExhausted: 429 ... free_tier_requests, limit: 20`). È una quota di
piattaforma (una chiave sola, condivisa da tutte le aziende collegate), non
per-azienda: 20 messaggi/giorno in totale sono pochissimi per un uso reale
anche di una sola azienda attiva, figuriamoci di più clienti come da
obiettivo dell'utente. Il fallback allo Stub gratuito rende il sistema
comunque funzionante quando la quota finisce (verificato: stessa richiesta,
stessa risposta corretta, nessun errore visibile all'utente finale) — ma
per un uso reale multi-azienda serve un piano Gemini a pagamento (limiti
molto più alti) o accettare che oltre le 20 richieste/giorno si torni al
riconoscimento a pattern gratuito.

### Previsione di cassa ✅ verificato (26 agosto 2026)
Prima idea "innovativa" proposta tempo fa (insieme a scadenzario fiscale e
spiegazioni automatiche — l'utente aveva scelto le spiegazioni per prime,
poi il feedback su usabilità/onboarding ha preso priorità) e oggi scelta
come prossimo passo. Fino ad ora Cortex mostrava solo la liquidità
*attuale* — questa è la prima funzione che guarda avanti.

`services/previsione.py` (nuovo, generico per entrambi i profili come
narrazione.py): proietta la liquidità attuale per i prossimi 3 mesi usando
il flusso di cassa netto medio (entrate - uscite) degli ultimi 6 mesi con
movimenti reali — non un modello di ML, una proiezione lineare semplice e
verificabile, costruita componendo funzioni già esistenti
(`compute_saldi`, `compute_spese_per_categoria`,
`ultimo_periodo_con_movimenti`) senza calcoli nuovi nei motori. Parte
dall'ultima attività contabile reale, non dal mese di calendario corrente
— stesso motivo di `spiega_ultimo_periodo_con_dati`: un'azienda la cui
contabilità si ferma a un anno fa altrimenti non avrebbe nessuno storico
recente da cui proiettare. Se la proiezione scende sotto zero, un
`avviso` esplicito indica da quale mese — il punto centrale della
richiesta originale ("avvisa prima che diventi un problema").

Esposto via `GET /accounting/previsione-cassa` (stesso pattern di
dispatch di `/spiegazione`), una nuova scheda "Previsione di cassa" in
Contabilità (grafico a card mese-per-mese + narrazione + banner rosso se
c'è un avviso), e un avviso compatto sulla Dashboard quando presente
(riusa lo stesso riepilogo già calcolato, nessuna chiamata in più) — solo
quando c'è davvero qualcosa da segnalare, niente banner quando tutto va
bene.

**Verificato con dati reali su entrambi i profili**: Sampeyre — flusso
medio -213,50€/mese (negativo, reale), proiezione a Novembre 2026 968,50€,
nessun avviso (non scende sotto zero in 3 mesi); Trevalli/Arca — flusso
medio +633,38€/mese, proiezione da Dicembre 2020 (ultima attività vera) a
Marzo 2021. **Verificata anche la logica di avviso** con un motore finto
(entrate 100€/mese, uscite 400€/mese, liquidità di partenza 500€): avviso
corretto "scenderebbe sotto zero a Ottobre 2026", proiezione -100€/-400€
nei mesi successivi. Verificato nel browser reale (Trevalli): scheda
"Previsione di cassa" in Contabilità con dati veri, nessun errore in
console; Dashboard senza banner quando non c'è avviso (nessuna
regressione).

Limite dichiarato esplicitamente nell'interfaccia, non nascosto: "non
tiene conto di eventi non ricorrenti attesi (una fattura grande in arrivo,
una spesa straordinaria pianificata)" — è un trend storico, non
un'previsione che conosce il futuro specifico dell'azienda.

### "Andamenti": analisi automatica, zero Viste/Segnalazioni da creare ✅ verificato (26 agosto 2026)
Feedback dell'utente: "le viste e le segnalazioni sono troppo difficili da
programmare, Cortex deve essere un software che lo fa in automatico che
mostra grafici tabelle e andamenti". Confermato con l'utente cosa
costruire (non un'ipotesi): non "rendere il configuratore più facile" —
eliminarlo per il caso comune. Colleghi un database, Cortex trova da solo
cosa mostrare.

`services/analisi_automatica.py` (nuovo): per un'integrazione qualunque —
nessun profilo contabile richiesto, funziona anche su uno schema mai
visto — scandaglia le tabelle e trova da sola quelle con una colonna data
e una colonna importo plausibili, mostrando un andamento mensile.
Tre passaggi per le performance, misurati su un database Arca reale (372
tabelle): un COUNT(*) grezzo per tabella scarta quelle vuote/quasi-vuote
(~3s per tutte le 372, nessuna reflection); `Inspector.get_columns()`
sulle rimanenti legge nomi/tipi colonna senza costruire l'oggetto Table
completo (~6s per tutte le 372, molto più leggero della reflection piena
misurata a 16s su una singola tabella larga); solo le poche tabelle che
passano entrambi i filtri vengono interrogate per i dati veri. Risultato
cacheato 30 minuti (stesso principio di db_engine.py).

**Tre problemi reali trovati provando su dati veri, non ipotetici**:
1. Un primo tentativo completo impiegava **75 secondi** — la causa non
   erano i filtri ma la reflection SQLAlchemy piena (`Table(...,
   autoload_with=...)`) rifatta per ognuna delle tabelle candidate, la
   stessa spesa da sempre nota (16s su una tabella larga) ma ora ripetuta
   12 volte. Corretto passando a costrutti "leggeri"
   (`sqlalchemy.table()`/`column()`, senza introspezione: generano SQL
   portabile — LIMIT, ORDER BY, quoting — senza nessuna chiamata al
   database per i metadati) per la sola query finale, dove bastano i nomi
   di due colonne già noti dal passaggio precedente. Da 75s a 2,8s.
2. Le colonne scelte erano spesso senza senso: `TimeIns` (un timestamp di
   audit interno — quando la riga è stata scritta nel database, non un
   fatto di business) usato come "data", `ContoMerceSpesa`/`TipoConto`
   (flag e codici, non importi) usati come "numero". Corretto escludendo
   esplicitamente le colonne di audit note e richiedendo che il nome della
   colonna importo *inizi* con una parola plausibile (non la contenga in
   coda: "spesa" dentro "ContoMerceSpesa" aveva fatto scegliere un flag al
   posto del vero importo, "ImportoE", nella stessa tabella).
3. Le query "leggere" del punto 1, non conoscendo il tipo della colonna,
   perdono la conversione automatica di SQLAlchemy da stringa a data — su
   SQLite (Sampeyre) una colonna DATE è memorizzata come testo, e ogni riga
   veniva scartata in silenzio: Sampeyre risultava "senza andamenti" pur
   avendo dati reali. Corretto con un parsing esplicito che gestisce sia
   oggetti data nativi (SQL Server via pyodbc) sia stringhe ISO (SQLite).

Aggiunti anche due filtri di qualità scoperti provando: un andamento con
un solo mese di dati non è un andamento (scartato), e una colonna trovata
per nome/tipo ma sempre a zero nei dati reali non viene mostrata (es.
`CS.ImportoMassimoDetraibile`, un campo reale ma vuoto in questo dataset).

Nuova pagina "Andamenti" (route `/andamenti`, voce di menu generica per
tutti i settori): un grafico per tabella trovata, nessuna configurazione.
L'endpoint (`GET /integrations/{id}/analisi-automatica`) ritorna
direttamente nella forma già pronta per WidgetCanvas — stesso principio
dei "modelli pronti" di Arca, zero rendering nuovo lato frontend.

**Verificato con dati reali su entrambe le aziende**: Sampeyre — un
grafico reale (`movimenti`, gennaio-agosto 2026, valori corretti
verificati riga per riga); Trevalli/Arca — tre grafici reali (CGMovR,
CGMovT, CGDatiFatturaR, con importi e mesi corretti) su 372 tabelle
scandagliate, in 2,8 secondi la prima volta e 20 millisecondi con la
cache. Verificato nel browser reale (Trevalli): tre grafici renderizzati
correttamente nella nuova pagina, nessun errore in console.

### "Quadro generale": la chat compone invece di scegliere da un menu ✅ verificato (26 agosto 2026)
Feedback dell'utente: "trovo ancora troppo poco utile la possibilità di
visionare grafici tramite la chat, ce di per sé sono solo dei template già
fatti — vorrei che in base a ciò che gli viene scritto si possa vedere un
tutto tondo dell'azienda". Punto giusto: `visualize_tool` sceglieva sempre
UNO tra 6 modi fissi (saldo/periodo/confronto/andamento/elenco/spiegazione)
— una domanda aperta come "come sta andando l'azienda?" veniva forzata in
uno di questi, perdendo tutto il resto.

Aggiunto un settimo modo, `quadro_generale`, che non è un grafico ma una
**composizione** di più cose già costruite e verificate separatamente —
liquidità attuale, cosa è cambiato, previsione di cassa, segnalazioni
aperte — tutte insieme in una sola vista, nello stesso identico costo di
UNA chiamata LLM (nessun giro aggiuntivo alla quota gratuita di Gemini: il
modello sceglie solo il modo, il resto sono funzioni locali già pronte —
`compute_saldi`, `spiega_ultimo_periodo_con_dati`, `previsione_liquidita`,
`valuta_tutte_le_regole` — nessun calcolo nuovo). Aggiunto sia allo schema
del tool per un LLM vero (con una descrizione che indica esplicitamente
quando usarlo: richieste generiche sulla salute dell'azienda, non su un
dato specifico) sia ai trigger di StubLLMClient ("quadro generale", "come
sta andando l'azienda", "panoramica", ecc.) — funziona anche a costo zero,
non solo con Gemini collegato. Nuovo tipo di widget "quadro_generale" in
WidgetCanvas.jsx, che mostra le quattro sezioni insieme in una sola card.

**Verificato con dati reali su tre percorsi diversi**: via StubLLMClient
diretto ("dammi un quadro generale dell'azienda" → tutte e quattro le
sezioni popolate con dati veri di Sampeyre, incluse le 4 segnalazioni
sui debitori scaduti); via Gemini con una **parafrasi libera** che non
contiene nessuna delle parole-chiave esatte ("fammi capire in generale
come sta messa l'azienda al momento" → riconosciuto correttamente come
`quadro_generale`, prova diretta che non è un altro trigger fisso ma una
vera comprensione dell'intento); e nel browser reale (Trevalli), dove il
widget composito si è renderizzato correttamente con tutte e quattro le
sezioni e i dati veri di Arca, nessun errore in console.

### Onboarding di una nuova azienda ✅ verificato (25 agosto 2026)
Feedback dell'utente: "non è per nulla abbastanza, trovo proprio che sia
difficile da usare". Invece di chiedere altri dettagli, ho registrato io
stesso un'azienda nuova da zero (mai vista da Cortex) e seguito il percorso
reale — due problemi concreti trovati, non ipotesi:

1. **La Dashboard di un'azienda appena registrata mostrava di nuovo i due
   zeri finti** ("Overview 0" / "Recent Activity 0") — lo stesso problema
   "sistemato" il 20 agosto, ma solo per aziende che hanno già
   un'integrazione contabile riconosciuta. Un'azienda nuova non ne ha
   ancora nessuna: cade sul vecchio fallback, senza nessuna indicazione su
   cosa fare. **Corretto**: `GET /dashboard` ora espone anche
   `numero_integrazioni`; se è zero, la Dashboard mostra un invito chiaro
   ("Inizia collegando la tua azienda") con spiegazione in una frase e un
   bottone diretto a Integrazioni, invece delle card finte.
2. **Il menu "Servizio" in Integrazioni mostrava 7 nomi tecnici grezzi**
   (gmail, stripe, openai, sql_erp, custom_db, cortex_managed_db, rest_api)
   senza nessuna spiegazione — un titolare d'azienda non tecnico non ha
   modo di sapere cosa scegliere. **Corretto**: aggiunte etichette in
   italiano e una riga di descrizione per ognuno in
   `integration_providers.py` (es. "Database creato da Cortex — consigliato
   se non hai nulla" invece di "cortex_managed_db"), riordinati mettendo
   prima le opzioni per collegare la propria contabilità (il caso comune)
   e dopo i servizi accessori (email, pagamenti, IA). L'opzione
   raccomandata ("database creato da Cortex") è ora anche quella
   selezionata di default aprendo il form, non più "gmail".

**Verificato end-to-end** registrando davvero "Officina Verifica Test" da
zero: Dashboard → invito chiaro invece di zeri finti → click su "Vai a
Integrazioni" → menu con etichette leggibili e descrizione visibile sotto
("Non hai ancora un gestionale? Cortex ne crea uno pronto all'uso in un
click..."). Nessun errore in console. Azienda di test ripulita a fine
verifica.

Non ancora affrontato in questo giro (la pagina Segnalazioni resta
oggettivamente tecnica da configurare — condition_type, config per tipo,
sintassi {{colonna}} — l'onboarding era il problema più urgente e più a
monte: prima che un'azienda nuova capisca come iniziare, il resto non
conta).

### Segnalazioni con anteprima live + scopribilità della chat ✅ verificato (25 agosto 2026)
Confermato dall'utente: "la parte di segnalazioni è molto utile però è
troppo difficile da usare" — più un secondo problema notato a parte:
"l'amministratore di un'azienda non può sapere quali grafici la chat può
mostrare e quali no". Due problemi distinti, risolti entrambi.

**Anteprima live per le Segnalazioni**: il punto più difficile non era la
forma del form (già ragionevole: guess automatico delle colonne, tipi in
italiano) ma configurare **alla cieca** — si salvava la regola e solo dopo,
andando a controllare "Segnalazioni attive" altrove nella pagina, si
scopriva se aveva preso qualcosa. Aggiunto `POST /alerts/anteprima`
(nuovo — non richiede una regola già salvata, valuta la condizione al volo
tramite `alert_engine.valuta_condizione`, nuova funzione pubblica estratta
dai valutatori già esistenti) e un riquadro che si aggiorna da solo
(con debounce, 400ms) mentre si sceglie tabella/colonna/soglia: "Con questi
criteri, oggi scatterebbero N segnalazioni: ...". Il ciclo di
configurazione ora si chiude subito, non dopo un salvataggio.

**Scopribilità della chat**: prima l'unico aiuto era un'unica riga
segnaposto, visibile solo prima del primo messaggio e sparita per sempre
dopo (anche ricaricando la pagina, se c'era già una conversazione). Un
amministratore non aveva modo di sapere i confini di un riconoscimento a
pattern (non un vero LLM): quali frasi funzionano, quali no. Aggiunto un
pulsante "Cosa posso chiederti?" sempre visibile nell'header della chat
(`AgentChat.jsx`) che apre un pannello categorizzato (soldi / email /
ricerca online) con esempi reali, più — dinamicamente — i nomi veri delle
Viste salvate dell'azienda ("mostrami [nome]"), non solo esempi generici
che potrebbero non applicarsi a quell'azienda.

**Verificato nel browser con dati reali**: selezionata l'integrazione
"Database Debitori (test)" e la tabella `debitori` nel form Segnalazioni —
l'anteprima ha mostrato subito "Con questi criteri, oggi scatterebbero 4
segnalazioni: scaduta da 41 giorni; scaduta da 56 giorni; scaduta da 24
giorni; scaduta da 5 giorni" (stessi 4 debitori già verificati altrove).
Pannello di aiuto della chat verificato aperto/chiuso, contenuto
categorizzato visibile. Nessun errore reale in console (solo un 404
transitorio auto-corretto durante un normale cambio di stato React, non un
bug).
### Chat: esplorazione libera + memoria conversazionale ✅ verificato (3 settembre 2026)
Feedback dell'utente: "la chat al momento è piuttosto inutile". Punto giusto,
confermato guardando il codice prima di rispondere: la chat sapeva rispondere
SOLO sui 7 modi fissi di `visualize_tool` (tutti sul dominio entrate/uscite
dei due motori contabili) e non aveva nessuna memoria tra un messaggio e
l'altro — ogni messaggio veniva deciso da solo, un "e il mese scorso?" dopo
aver chiesto i saldi di agosto non funzionava. Un'azienda con uno schema non
riconosciuto (né Sampeyre né Arca) non aveva NESSUNA delle due cose in chat,
indipendentemente da quanti dati avesse.

**Esplorazione libera** (nuovo `services/esplorazione.py` + tool
`esplora_tool`): qualunque domanda che non riguarda entrate/uscite/liquidità
("quanti clienti abbiamo?", "quante fatture...") ora prova a cercare una
risposta vera tra le tabelle del database collegato, non solo nei due motori
contabili. Due livelli: prima tra le tabelle che `analisi_automatica` (la
stessa di Andamenti) ha già trovato "interessanti" — risposta più ricca, un
vero andamento mensile; altrimenti tra TUTTE le tabelle del database — solo
conteggio ed eventuale somma di una colonna numerica plausibile. Mai
un'invenzione: se nessuna tabella sembra pertinente, risponde onestamente
elencando quelle che sa leggere, invece del vecchio vicolo cieco
("L'assistente che risponde davvero sulle tue cifre arriva nel prossimo
passo della Fase D" — questo *è* quel passo). Matching per token, non
un'unica sottostringa: spacca i nomi tabella in CamelCase/PascalCase
(gestisce sia "CGDatiFatturaR" → cg/dati/fattura/r sia — bug trovato provando
dal vivo — "VBCliente", dove non esiste nessun confine minuscola→maiuscola:
serviva una seconda regola per il confine sigla-poi-parola) e confronta le
radici con le parole della domanda, scartando le stopword italiane.

**Memoria conversazionale** (nuovo `services/conversation_state.py`, stesso
principio in-memory di `agent_state.py`): le ultime 6 battute per utente,
passate come contesto sia a un LLM vero (Gemini/OpenAI ora ricevono la
cronologia multi-turno, non solo l'ultimo messaggio) sia — per "il mese
scorso/prima" — a `StubLLMClient`, che eredita modo/tipo dall'ultima
richiesta di visualizzazione risolta con successo e sposta solo il periodo.

**Bug di affidabilità trovato e corretto provando dal vivo**: senza un
timeout esplicito, una chiamata a Gemini che rallenta (rate limit del piano
gratuito, non un errore vero e proprio) blocca la richiesta HTTP per oltre un
minuto invece di far scattare il ripiego silenzioso su StubLLMClient già
esistente (`AgentBrain._decidi_con_ripiego` intercetta solo le eccezioni, non
la lentezza) — riprodotto due volte dal vivo (`quanti clienti abbiamo?` su
Trevalli, bloccato oltre 60 secondi). Aggiunto un timeout di 12 secondi sia a
`GeminiLLMClient` sia a `OpenAILLMClient`: un timeout ora conta come un
fallimento del provider a tutti gli effetti, il ripiego scatta sempre.

**Verificato con dati reali su entrambe le aziende**: Trevalli — "quante
fatture abbiamo emesso?" trova da solo `CGDatiFatturaR` e mostra l'andamento
mensile reale (224 fatture, importi 2018 corretti); "quanti clienti abbiamo?"
trova `VBCliente` e mostra il conteggio reale (0 righe, tabella
genuinamente vuota in questo dataset di test). Sampeyre — "quanti volontari
abbiamo?" risponde onestamente "Non ho trovato dati su... Le tabelle che
riesco a leggere sono: movimenti" invece di un vicolo cieco. Memoria
verificata nel browser reale (non solo via API): "mostrami le spese di
luglio 2026" → widget Luglio; "e il mese scorso?" → widget Giugno con numeri
reali diversi (148€/45€ invece di 152€/42€); un secondo "e il mese scorso?"
di seguito → Maggio — la catena funziona anche quando la prima richiesta è
stata risolta da Gemini e la seconda, per un fallimento reale del provider
durante il test, è caduta sul ripiego StubLLMClient: il contesto salvato
server-side (non legato a quale client ha risposto) ha retto lo stesso.
Pannello "Cosa posso chiederti?" aggiornato con la nuova categoria e
verificato aperto nel browser con il contenuto nuovo. Nessun errore in
console, nessuna regressione sui modi esistenti (saldo, quadro_generale,
email con conferma) riverificati dopo la modifica.

### Ruoli utente: admin / sola lettura ✅ verificato (3 settembre 2026)
Discussione più ampia su cosa manca per essere vendibile a più aziende reali
(ognuna con più di una persona) — scelto di partire da qui perché, a
differenza di sostenibilità Gemini/deploy/billing, è un vuoto puramente
tecnico: prima chiunque avesse una Membership per un'azienda aveva accesso
identico e totale a tutto, senza modo di dare a un dipendente del cliente un
accesso di sola consultazione.

**Due ruoli** (`models/membership.py`, campo `role` su `Membership` — non su
User: la stessa persona può essere admin della propria azienda e sola
lettura in un'azienda cliente a cui è stata invitata, o viceversa): "admin"
può tutto quello che si poteva fare finora; "readonly" consulta
dashboard/andamenti/contabilità/chat ma non modifica nulla di persistente né
invia nulla verso l'esterno. Applicato con una dependency FastAPI condivisa
(`api/deps.require_admin`) su ogni endpoint che crea/modifica/elimina
qualcosa o manda un'email: integrazioni (create/update/delete), regole di
segnalazione (create/delete), Viste (create/delete), scrittura sul Data
Explorer (righe + import quando `esegui=true`, non l'anteprima), conferma di
un'azione pendente sia dalla chat (`/agent/confirm`) sia da Segnalazioni
(`/azioni-pendenti/.../conferma` e `/rifiuta`), gestione team (rigenera
invito, cambia ruolo). Rimasto aperto a tutti: leggere ovunque, la chat
(anche `esplora_tool`/`visualize_tool` — solo *inviare* un'email è riservato,
prepararne la bozza no), l'anteprima di una regola prima di salvarla,
l'anteprima di un import CSV.

**Di default chi si unisce con il codice invito parte "sola lettura"**
(prima diventava un admin alla pari) — un admin esistente lo promuove dalla
pagina Team se serve. Eccezione deliberata: `join_organization` (un utente
Cortex già esistente che comincia a seguire un'altra azienda cliente, il
caso "consulente con più clienti" del Portfolio) resta admin, perché è un
flusso diverso in natura da "nuovo dipendente si iscrive per la prima
volta" — stesso codice invito, endpoint diverso, scelta diversa. Le
Membership già esistenti sono rimaste "admin" con la migrazione (nessuno
perde accesso che aveva già): la regola più severa vale solo da qui in poi.

Corretto anche, nello stesso giro perché la stessa riscrittura di
`api/team.py` serviva comunque per mostrare il ruolo di ciascuno, un bug già
noto e segnalato più volte: la pagina Team mostrava solo gli utenti la cui
azienda ATTIVA in quel momento combaciava (`User.organization_id`), non
tutti i membri veri secondo Membership — un membro che stava guardando
un'altra delle sue aziende spariva dall'elenco pur avendo ancora accesso.

**Protezione contro un'azienda senza più nessun admin**: non si può
retrocedere l'ultimo amministratore rimasto (l'endpoint rifiuta con 400,
"promuovi prima qualcun altro") — altrimenti nessuno potrebbe più gestire
l'azienda, nemmeno tornare admin da solo.

**Verificato con chiamate reali, non solo per costruzione**: un utente
registrato con l'invito di Sampeyre riceve davvero `role: "readonly"`;
prova a creare un'integrazione → 403 "Serve un ruolo di amministratore per
questa azione"; legge la dashboard e usa la chat (saldo) → 200, dati veri.
Promosso ad admin dalla pagina Team → può di nuovo creare. Su un'azienda con
un solo membro (org di test "Azienda Estranea Srl"), il tentativo di
autoretrocedersi viene rifiutato con il messaggio corretto. Nel browser
reale (non solo via API): Integrazioni/Segnalazioni/Viste mostrano un avviso
"Sei in sola lettura..." al posto dei form e nascondono
rinomina/elimina/conferma/scarta; la pagina Team mostra i ruoli come testo
semplice (niente selettore) per chi non è admin, e come menu a tendina per
chi lo è; il badge "Sola lettura" compare nella Topbar su ogni pagina.
Nessun errore in console, nessuna regressione sulle pagine non toccate.

**Aggiornamento (3 settembre 2026, stesso giorno)**: chiuso anche il Data
Explorer. Nascosti per un utente sola lettura: la riga per aggiungere una
nuova riga, le icone modifica/elimina su ogni riga, il bottone "Conferma
import" (l'anteprima dell'import resta aperta, non scrive nulla — stesso
principio di Segnalazioni). Aggiunto un avviso "Sei in sola lettura..."
sopra la tabella. Verificato nel browser reale con l'utente di test: la
tabella `categorie` di Sampeyre si legge ed esporta normalmente, nessuna
riga/pulsante di scrittura visibile, l'avviso compare; da admin tutto torna
come prima. Nessun errore in console.

### Prima suite di test automatici ✅ verificato (3 settembre 2026)
Fino a qui ogni verifica è stata manuale — reale, seria, ma manuale: due bug
di questa stessa sessione (la tokenizzazione di "VBCliente", il blocco di
Gemini senza timeout) sono stati trovati solo perché provati a mano nel
momento giusto. Discussione più ampia su cosa migliorare dopo i ruoli:
scelto di costruire una prima rete di sicurezza automatica prima di
continuare ad aggiungere feature sopra una base cresciuta parecchio
(motore contabile duale, 3 livelli di LLM, esplorazione libera, ruoli).

**`backend/tests/`, pytest + FastAPI TestClient** (nuove dipendenze solo di
sviluppo, `requirements-dev.txt`, non toccano `requirements.txt` che serve
anche in produzione). Ogni test usa un database SQLite isolato (in memoria
per l'app Cortex vera, un file temporaneo per i fixture dei motori
contabili) — mai `cortex_enterprise.db`, il database reale con
Sampeyre/Trevalli/tutti i dati con cui lavoriamo. `TestClient(app)`
istanziato senza il context manager `with`, apposta: evita di far scattare
il lifespan di FastAPI, che altrimenti avvierebbe lo scheduler in
background puntato sul database vero.

**93 test, ~12 secondi**, sei file:
- `test_auth_roles.py` (24 test) — registrazione, login, e soprattutto i
  permessi appena costruiti: ogni endpoint che modifica qualcosa rifiuta
  un utente sola lettura con 403; non si può retrocedere l'ultimo admin;
  la pagina Team mostra tutti i membri veri, non solo chi ha quell'azienda
  attiva in questo momento (lo stesso bug corretto insieme ai ruoli).
- `test_stub_llm.py` (21 test) — tutti i rami del riconoscimento a pattern
  gratuito: i 7 modi di visualize_tool, email, ricerca, il nuovo
  esplora_tool di fallback, i riferimenti relativi di periodo.
- `test_esplorazione.py` (11 test) — **con un test di regressione esplicito
  per il bug reale "VBCliente"** trovato provando su Trevalli poche ore fa:
  senza un test, un domani qualcuno potrebbe "semplificare" il tokenizer e
  farlo tornare senza che nessuno se ne accorga.
- `test_analisi_automatica.py` (13 test) — **regressioni esplicite per
  TimeIns e ContoMerceSpesa**, i due bug reali trovati il 26 agosto su un
  database Arca vero, più i due filtri di qualità (data sentinella futura,
  colonna sempre a zero).
- `test_alert_engine.py` (11 test) — le tre condizioni di Segnalazione.
  Scoperta minore mentre si scriveva un test: con esattamente 4 valori
  "normali" (il campione minimo) più un outlier, lo z-score massimo
  raggiungibile è matematicamente sempre sotto una soglia di 2 deviazioni
  standard, qualunque sia la grandezza dell'outlier — non un bug, una
  proprietà statistica di `pstdev` su campioni piccoli, ma buona da sapere.
- `test_accounting_sampeyre.py` (8 test) + `test_llm_client_helpers.py`
  (13 test) — il motore contabile Sampeyre su un fixture con lo schema
  reale, e le trasformazioni pure attorno ai client LLM (conversione
  protobuf→Python di Gemini, cronologia multi-turno).

**Deliberatamente non coperto**: il profilo Arca (richiede un vero SQL
Server) e le chiamate vere a Gemini/OpenAI (rete, a pagamento) restano
verificati a mano come finora — automatizzarli non varrebbe il costo.
Dettagli e comando per lanciarli in `backend/tests/README.md`.

### Viste e Segnalazioni create da sole dalla chat ✅ verificato (3 settembre 2026)
Feedback dell'utente, di nuovo: "così è troppo troppo difficile da usare".
Ripassate le pagine con occhi nuovi (non solo Segnalazioni, già segnalata
più volte: anche "I miei clienti", che parla da consulente/rivenditore
anche a chi ha una sola azienda, e "Viste", che mostra ancora nomi tabella
grezzi e sintassi `{{colonna}}`). L'utente ha rilanciato con un'idea più
grande: "l'utente vorrebbe vedere la tabella dei debitori e in automatico
l'IA va a creare la vista perfetta e più opportuna" — e la stessa cosa per
le Segnalazioni. Confermata la Fase 1 (Viste/Segnalazioni automatiche,
sicura perché non scrive sui dati) prima delle fasi più delicate (scrittura
via chat con conferma, import da chat, lettura foto — rimandate).

**`services/vista_automatica.py`**: "mostrami i debitori" trova la tabella
(riusa la stessa ricerca dell'esplorazione libera, qui su TUTTE le tabelle
non solo quelle con un andamento), decide da sola la modalità — "calendar"
se c'è sia una colonna data sia una testuale plausibile da usare come
titolo dell'evento (stesse euristiche di Andamenti), altrimenti "table",
l'unica che funziona sempre — e salva una Vista vera, non una risposta
usa-e-getta. Idempotente: richiesta due volte, la seconda riusa la stessa
Vista invece di duplicarla; dopo la prima creazione, "mostrami debitori"
richiama la Vista salvata per nome (`_try_saved_view`, già esistente) senza
nemmeno passare più dall'LLM/euristica.

**`services/segnalazione_automatica.py`**: stesso principio ma per le
Segnalazioni, ristretto DELIBERATAMENTE al tipo "scadenza_superata" — è
l'unico abbastanza riconoscibile da una frase libera ("è scaduto", "è in
ritardo"); dedurre da testo libero colonna e soglia per "soglia_numerica" o
capire quando serve "valore_anomalo" è troppo ambiguo, una regola indovinata
male è peggio di nessuna regola — chi ha bisogno di quei due tipi resta sul
configuratore manuale, che li fa già bene. Mostra subito, nella stessa
risposta, quante righe scatterebbero oggi con i criteri appena creati.

Due nuovi tool (`crea_vista_tool`, `crea_segnalazione_tool`) accanto a
`esplora_tool`, con la stessa distinzione di StubLLMClient: "mostrami/dammi
X" → intenzione di vedere (e riusare) qualcosa, vale la Vista; "avvisami/
segnalami quando X è scaduto/in ritardo" → la Segnalazione; tutto il resto
resta su `esplora_tool` (una domanda puntuale, nessuna persistenza).

**Verificato con una chiamata reale end-to-end**, non solo per costruzione
— creata un'azienda di prova con una vera tabella `debitori` (nome,
scadenza, importo_dovuto, 4 righe, 3 scadute): "mostrami i debitori" →
Vista "Debitori" creata in modalità calendario, colonna data "scadenza",
titolo "nome", 4 eventi reali sul calendario; "avvisami quando un debitore
è scaduto" → Segnalazione "Debitori scaduti" creata, "oggi scatterebbe su 3
righe" (i 3 realmente scaduti, non il quarto con scadenza 2099); richiesto
di nuovo "mostrami debitori" → risposta `action: "saved_view"`, non più
`crea_vista_tool`, conferma che il percorso veloce scatta dalla seconda
volta in poi. Nel browser reale: il widget calendario si vede con "Mario
Rossi" sul 20 giugno, e le 3 segnalazioni appena create compaiono anche
nel pannello Segnalazioni della Dashboard, segno che sono regole vere e
proprie, non un side-effect isolato. Aggiunti 7 test automatici
(`tests/test_creazione_automatica.py`), suite totale ora a 100 test.

Non ancora affrontato in questo giro (fasi successive, rimandate su scelta
esplicita dell'utente): insert/update/delete via chat con conferma, import
di file dalla chat, lettura di foto/scontrini. Restano anche aperti "I miei
clienti" (linguaggio da consulente mostrato a tutti) e la sintassi
`{{colonna}}` nelle azioni di riga di Viste/Segnalazioni.

### Chiusi gli ultimi due punti di usabilità in sospeso ✅ verificato (3 settembre 2026)
I due punti rimasti aperti dal giro di revisione con "occhi nuovi" di prima.

**"I miei clienti" non parla più a chi ha una sola azienda**: la voce di
menu (e la pagina, se raggiunta da un link diretto) ora si adattano a
`organizations.length` (già disponibile in AuthContext) — chi ha una sola
azienda non la vede più in Sidebar, e se ci arriva comunque trova "Segui
un'altra azienda" con un testo che non presume un rapporto da
consulente/cliente, invece della propria azienda mostrata come se fosse
"un cliente da seguire". Chi ne ha più di una vede tutto come prima, invariato
(verificato con entrambi i casi nel browser reale, stesso account).

**Niente più sintassi `{{colonna}}` da scrivere a mano**: nuovo componente
`InserisciCampo` (chip cliccabili, un bottone per colonna disponibile) sotto
ogni campo di testo che supporta segnaposto — il messaggio di una
Segnalazione, l'oggetto/testo delle sue azioni automatiche, l'oggetto/testo
delle azioni di riga di una Vista. Un click aggiunge `{{colonna}}` in coda
al testo esistente (con uno spazio se non è vuoto): l'utente non deve più
sapere che quella sintassi esiste. Verificato cliccando davvero i chip nel
browser: "nome" poi "codice" sul campo Oggetto di un'azione di Vista
producono `{{nome}} {{codice}}`, esattamente come scrivendoli a mano ma
senza dover conoscere la sintassi.

### Segnalazioni automatiche: aggiunto il caso "soglia numerica" + due bug reali di matching ✅ verificato (3 settembre 2026)
Bug reale segnalato dall'utente: "crea una segnalazione per le spese
maggiori di 1000 euro" su Trevalli rispondeva "Non ho trovato dati su ...",
elencando le tabelle di Andamenti (CGMovR, CGMovT, CGDatiFatturaR) — cadeva
su `esplora_tool` invece che sulla creazione di una Segnalazione, perché
`crea_segnalazione_tool` copriva solo il caso "scadenza_superata" (scelta
deliberata di scope della sessione precedente), e questa è una richiesta di
tipo "soglia_numerica".

**Aggiunto il secondo tipo**: `crea_o_riusa_segnalazione_soglia` in
`services/segnalazione_automatica.py`, stesso principio della scadenza ma
con colonna NUMERICA plausibile (stessa euristica di Andamenti) invece che
data, e `operatore`/`soglia` dedotti dal chiamante (mai indovinati qui).
`valore_anomalo` resta escluso, stessa ragione di prima (troppo ambiguo da
testo libero). Nuovo riconoscimento in `StubLLMClient`: richiede sia una
parola di segnalazione/avviso sia un confronto numerico esplicito
(`_SOGLIA_RE`, "maggiore/superiore/sopra/oltre di N" → ">", "minore/
inferiore/sotto di N" → "<") — così "le spese sono maggiori di 1000" (una
semplice osservazione, non una richiesta) non scatena una creazione.

**Bug di correttezza trovato scrivendolo**: riusare una regola già
esistente in base a sola tabella+tipo avrebbe fatto ignorare silenziosamente
una soglia diversa chiesta una seconda volta ("maggiori di 500" dopo un
"maggiori di 1000" già creato sarebbe rimasto sulla vecchia soglia). Corretto
riusando solo a parità di configurazione ESATTA (tabella+tipo+colonna+
operatore+soglia) — una soglia diversa crea una regola nuova e distinta,
non aggiorna quella vecchia.

**Due bug di matching reali trovati provando dal vivo, uno causato
dall'altro**: (1) "spesa"/"spese" — 5 lettere ciascuna — non venivano
riconosciute come la stessa parola: il confronto a prefisso pieno
richiedeva tutte e 5 le lettere uguali e falliva sull'ultima (differenza
singolare/plurale). Corretto ignorando l'ultima lettera del confronto.
(2) Allentare quel confronto ha aperto un secondo bug subito dopo: "spese"
ha iniziato a combaciare anche con "CGSpesometroR" (un adempimento fiscale,
tutt'altra cosa) per pura coincidenza delle prime 4 lettere. Corretto
aggiungendo un vincolo sulla differenza di lunghezza (max 2): un vero
singolare/plurale italiano non si allunga così tanto. `_radice_comune`
in `services/esplorazione.py`, usata sia dall'esplorazione libera sia dalla
creazione automatica di Viste/Segnalazioni — il fix vale per tutte e tre.

**Verificato con la frase esatta dell'utente, sull'account Trevalli reale**:
prima del fix, esattamente il comportamento segnalato (vicolo cieco su
esplora_tool); dopo il primo fix, un falso positivo su CGSpesometroR (0
righe, ma la tabella sbagliata); dopo il secondo fix, "DORigSpesa sopra
1000" — una vera tabella di righe spesa di Arca, con la colonna ImportoV
scelta correttamente. "0 righe" verificato essere corretto e non un
sintomo di colonna sbagliata: la tabella è genuinamente vuota in questo
dataset dimostrativo (0 righe totali, controllato direttamente). Aggiunti
10 nuovi test automatici (soglia numerica + regressioni di matching), suite
totale ora a 110 test.

### Basta template: la chat ragiona sullo schema reale invece di scegliere tra casi previsti in anticipo ✅ verificato (3 settembre 2026)
Critica di fondo dell'utente, dopo aver visto "soglia numerica" aggiunta a
mano subito dopo "scadenza": "non deve usare template predefiniti ma la
chat deve capire qualsiasi cosa voglia l'utente e farlo". Punto giusto: ogni
volta che una frase non rientrava in un caso previsto, la risposta era
scrivere codice per un caso in più — un tapis roulant che non finisce mai,
perché StubLLMClient (riconoscimento a parole chiave) non può
strutturalmente "capire qualsiasi cosa", e anche un LLM vero (Gemini)
veniva comunque instradato dentro parametri decisi in anticipo da me
(operatore/soglia dedotti da un'espressione regolare, mai le colonne reali
della tabella).

**Il cambio vero**: `AgentBrain._tabella_candidata()` pre-cerca (economico:
solo sui nomi tabella, nessuna query dati) la tabella pertinente PRIMA di
chiedere a un LLM cosa fare, ne legge le colonne reali, e le inietta nel
prompt di sistema (`llm_client._istruzioni_sistema`) sia per Gemini sia per
OpenAI. `crea_segnalazione_tool` e `crea_vista_tool` non hanno più
parametri fissi per "caso 1"/"caso 2": un LLM vero sceglie da solo
`condition_type` tra tutti e tre quelli che alert_engine sa valutare
(inclusa "valore_anomalo", prima IRRAGGIUNGIBILE dalla chat — nessuna
espressione regolare sapeva riconoscerla) e il nome ESATTO di una colonna
vera, o la modalità di una Vista (inclusa "cards", mai proposta
dall'euristica di base). Ogni colonna indicata viene comunque validata
contro lo schema reale prima di fidarsene — un LLM può sbagliare un nome,
e non deve mai bastare la sua parola su dati veri: se non esiste, si
ripiega sull'euristica automatica (stessa di Andamenti), non si fallisce e
non si inventa nulla. `services/segnalazione_automatica.py` e
`vista_automatica.py` riscritte attorno a una funzione generica
(`crea_o_riusa_segnalazione`) di cui le vecchie "_scadenza"/"_soglia"
restano thin wrapper — il ripiego onesto per StubLLMClient, che non
ragiona e non potrà mai raggiungere "valore_anomalo" o "cards": un limite
del livello gratuito, non di questo modulo.

**Due bug reali trovati provando dal vivo, non per costruzione**:
1. Regressione statistica già nota (campione troppo piccolo per superare 2
   deviazioni standard) ritrovata scrivendo i nuovi test — stesso fix di
   prima (più righe "normali" nel campione).
2. **Bug di tie-breaking in `_migliore`**: cercare letteralmente il nome
   esatto di una tabella ("CGDatiFatturaR") trovava una tabella DIVERSA
   ("CGDatiFatturaE") — le due producono lo stesso insieme di token (la
   lettera finale che le distingue, R vs E, è troppo corta per essere un
   token da sola), e a parità di punteggio vinceva solo chi veniva prima
   nell'elenco. Corretto con una scorciatoia: nome esatto (a meno di
   maiuscole) vince sempre, prima ancora del confronto a token.

**Limite onesto rimasto, non risolto in questo giro**: "fatture" da solo
(senza il nome esatto di una tabella) resta genuinamente ambiguo tra tre
tabelle Arca simili (CGDatiFatturaE/R/T — rispettivamente un log di scambio
XML senza colonne numeriche, i dati ricevuti, quelli presumibilmente
trasmessi) e il matching ne sceglie solo una, non necessariamente la più
sensata; verificato dal vivo che sceglie quella senza colonne numeriche,
la richiesta fallisce onestamente ("non ho trovato una tabella con una
colonna adatta") invece di creare una regola su una colonna sbagliata — ma
non prova le altre due tabelle candidate prima di arrendersi. Risolverlo
per bene richiederebbe dare a un LLM vero l'elenco COMPLETO delle tabelle
candidate (non solo la migliore) per farlo scegliere lui, un giro di
lavoro più grande rimandato.

**Verificato con dati reali su Trevalli**: passando il nome esatto della
tabella e la colonna reale (simulando cosa manderebbe un LLM vero che ha
visto lo schema), creata una vera Segnalazione "valore_anomalo" sulle
fatture — 11 righe reali scattate, con dettaglio statistico vero (es.
"Importo = 11298.2, media 737.52, scarto 4.8x la deviazione standard") —
un tipo di segnalazione che prima di oggi non era MAI stato raggiungibile
dalla chat, con nessuna combinazione di parole. Provato anche con Gemini
vero su frasi ambigue ("avvisami se una fattura ha un importo anomalo"):
ha scelto `esplora_tool` invece di creare la segnalazione — una vera
decisione dell'IA (nessun errore/timeout nei log), non del tutto quella
attesa: il meccanismo tecnico funziona, la scelta finale resta comunque
soggetta al giudizio del modello e alla formulazione del prompt, non
perfettamente prevedibile — onesto da segnalare, non nascosto. Suite di
test a 120 (8 nuovi test per il caso generico + la regressione di
matching).

- **Fase D2**: categorizzazione automatica, lettura fatture/scontrini,
  bilanci commentati — richiede un provider LLM vero e più stabile di quello
  gratuito attuale (deciso di rimandare).
- **Fase E**: backup automatico cloud + export Excel/PDF, cattura scontrini
  via email.
- **Fase F**: test con dati reali Sampeyre, formazione, avvio definitivo.
- **SQL Server (Arca)**: `pyodbc` pronto, manca il driver Microsoft ODBC 18 —
  da installare e verificare quando l'utente avrà il db locale pronto.
