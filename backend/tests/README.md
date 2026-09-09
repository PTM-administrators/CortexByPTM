# Test automatici

Prima volta:

```bash
cd backend
pip install -r requirements-dev.txt
```

Per lanciare tutti i test:

```bash
cd backend
python3 -m pytest
```

(`python3 -m pytest`, non solo `pytest`: aggiunge la cartella corrente a
`sys.path`, altrimenti `import app...` non si risolve.)

## Cosa copre

- **`test_auth_roles.py`** — registrazione (nuova azienda = admin, con
  invito = sola lettura), login, `/me`, `switch/join/create-organization`, e
  soprattutto i permessi: ogni endpoint che modifica qualcosa deve rifiutare
  un utente "sola lettura" con 403 e accettare un admin. La parte più
  delicata da avere protetta: qui un bug non è "un grafico sbagliato", è "un
  utente sola lettura che riesce a scrivere".
- **`test_stub_llm.py`** — tutti i rami di `StubLLMClient.decide_action`
  (il riconoscimento a pattern gratuito): i 7 modi di `visualize_tool`,
  email, ricerca, il nuovo `esplora_tool` di fallback, i riferimenti
  relativi ("il mese scorso").
- **`test_esplorazione.py`** — il tokenizer e il matching dell'esplorazione
  libera, incluso un test di regressione esplicito per il bug reale
  "VBCliente" trovato provando su Trevalli (vedi PLAN.md, 3 settembre 2026).
- **`test_analisi_automatica.py`** — le euristiche di Andamenti (colonna
  data/numerica plausibile), inclusi due test di regressione per bug reali
  trovati su Arca (TimeIns, ContoMerceSpesa) e per i filtri di qualità
  dell'andamento (data sentinella futura, colonna sempre a zero).
- **`test_alert_engine.py`** — le tre condizioni di Segnalazione
  (scadenza superata, soglia numerica, valore anomalo).
- **`test_accounting_sampeyre.py`** — il motore contabile del profilo
  Sampeyre (saldi, spese per categoria, andamento mensile) su un fixture
  SQLite con lo schema reale.
- **`test_llm_client_helpers.py`** — le trasformazioni pure attorno ai
  client LLM reali: la conversione protobuf→Python di Gemini (incluso il
  bug reale dei float interi), la costruzione della cronologia multi-turno.

## Cosa NON copre (scelta deliberata)

Il profilo Arca (`accounting_engine_arca.py`) richiede un vero SQL Server:
resta verificato manualmente come finora (vedi PLAN.md), non automatizzato
qui — costruire un SQL Server finto solo per i test non vale il costo.
Stesso discorso per le chiamate VERE a Gemini/OpenAI (rete, a pagamento):
solo le funzioni pure che le circondano sono testate qui, non la chiamata
in sé.
