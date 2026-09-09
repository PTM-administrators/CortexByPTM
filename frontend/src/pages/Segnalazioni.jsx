// Segnalazioni proattive: regole configurabili una volta (scadenza superata,
// soglia numerica, valore anomalo) che l'agente valuta da solo sui dati
// collegati — senza che serva chiedere in chat. Generico per qualunque
// settore e sorgente dati (database o API, vedi Integrazioni), sullo stesso
// principio delle Viste: configura una volta, riusa sempre.
import { useEffect, useState } from "react";
import { BellRing, Mail, Trash2, Check, X } from "lucide-react";
import Sidebar from "../components/layout/Sidebar";
import Topbar from "../components/layout/Topbar";
import InserisciCampo from "../components/ui/InserisciCampo";
import { useAuth } from "../context/AuthContext";
import api from "../services/api";

// Aggiunge {{colonna}} in coda al testo attuale invece di richiedere che
// l'utente sappia scrivere la sintassi a mano (vedi InserisciCampo).
function aggiungiSegnaposto(valoreAttuale, colonna) {
  return `${valoreAttuale}${valoreAttuale ? " " : ""}{{${colonna}}}`;
}

// Indizio di partenza per il destinatario dell'azione automatica — stessa
// idea di INDIZI_DATA/INDIZI_NUMERICI qui sopra, solo un suggerimento.
const INDIZI_EMAIL = ["email", "mail", "posta"];

const TIPI = [
  { value: "scadenza_superata", label: "Scadenza superata (una data nel passato)" },
  { value: "soglia_numerica", label: "Soglia numerica (un valore sopra/sotto un limite)" },
  { value: "valore_anomalo", label: "Valore anomalo (si scosta dalla media)" },
];

// Stessa idea di indovinaColonna in Viste.jsx: un punto di partenza plausibile
// guardando nome (e per i numeri, anche tipo) della colonna, non una certezza.
const INDIZI_DATA = ["data", "date", "scadenza", "giorno", "quando", "appuntamento"];
const INDIZI_NUMERICI_TIPO = ["int", "float", "real", "numeric", "decimal", "double"];
const INDIZI_NUMERICI_NOME = ["importo", "prezzo", "totale", "quantita", "valore", "costo", "spesa", "somma"];
const INDIZI_GRUPPO = ["categoria", "tipo", "stato", "status", "category"];

function indovinaPerNome(colonne, parole) {
  for (const parola of parole) {
    const trovata = colonne.find((c) => c.toLowerCase().includes(parola));
    if (trovata) return trovata;
  }
  return "";
}

function indovinaColonnaData(schema) {
  return indovinaPerNome(
    schema.map((c) => c.name),
    INDIZI_DATA
  );
}

function indovinaColonnaNumerica(schema) {
  // Una chiave primaria è quasi sempre numerica ma non è mai un valore su cui
  // ha senso calcolare soglie o medie — esclusa dal suggerimento.
  const candidate = schema.filter((c) => !c.primary_key);
  const perTipo = candidate.find((c) => INDIZI_NUMERICI_TIPO.some((t) => c.type.toLowerCase().includes(t)));
  if (perTipo) return perTipo.name;
  return indovinaPerNome(
    candidate.map((c) => c.name),
    INDIZI_NUMERICI_NOME
  );
}

function configDefault(tipo, schema) {
  if (tipo === "scadenza_superata") {
    return { colonna_data: indovinaColonnaData(schema), giorni_tolleranza: 0 };
  }
  if (tipo === "soglia_numerica") {
    return { colonna: indovinaColonnaNumerica(schema), operatore: ">", soglia: 0 };
  }
  if (tipo === "valore_anomalo") {
    return {
      colonna: indovinaColonnaNumerica(schema),
      colonna_gruppo: indovinaPerNome(schema.map((c) => c.name), INDIZI_GRUPPO),
      soglia_deviazioni: 2,
    };
  }
  return {};
}

export default function Segnalazioni() {
  const { user } = useAuth();
  // Creare/eliminare regole e confermare/scartare azioni pronte richiede un
  // ruolo admin (vedi backend/app/models/membership.py) — l'anteprima live
  // resta visibile a chiunque mentre compila il form, solo il salvataggio è
  // riservato.
  const isAdmin = user?.role === "admin";
  const [integrations, setIntegrations] = useState([]);
  const [rules, setRules] = useState([]);
  const [segnalazioni, setSegnalazioni] = useState([]);
  const [error, setError] = useState("");
  const [caricandoSegnalazioni, setCaricandoSegnalazioni] = useState(false);

  const [integrationId, setIntegrationId] = useState(null);
  const [tables, setTables] = useState([]);
  const [tableName, setTableName] = useState("");
  const [schema, setSchema] = useState([]);
  const [conditionType, setConditionType] = useState("scadenza_superata");
  const [name, setName] = useState("");
  const [config, setConfig] = useState({});
  const [messaggioTemplate, setMessaggioTemplate] = useState("");
  const [saving, setSaving] = useState(false);

  // Azione automatica (opzionale): se configurata, ogni segnalazione nuova
  // di questa regola prepara anche una bozza pronta (es. un sollecito) —
  // non solo la notifica interna. Nascosta dietro un interruttore: la
  // maggior parte delle regole non ne ha bisogno (non tutte le tabelle
  // hanno un indirizzo a cui scrivere).
  const [mostraAzione, setMostraAzione] = useState(false);
  const [azioneToColonna, setAzioneToColonna] = useState("");
  const [azioneOggetto, setAzioneOggetto] = useState("");
  const [azioneCorpo, setAzioneCorpo] = useState("");

  const [azioniPendenti, setAzioniPendenti] = useState([]);
  const [caricandoAzioni, setCaricandoAzioni] = useState(false);
  const [confermandoId, setConfermandoId] = useState(null);

  // Anteprima live: quante righe scatterebbero ORA con questi criteri,
  // mentre si sta ancora configurando — non dopo aver salvato. Il punto più
  // difficile segnalato dall'utente era configurare alla cieca e scoprire
  // solo dopo (andando a controllare "Segnalazioni attive" altrove) se la
  // regola faceva quello che doveva.
  const [anteprima, setAnteprima] = useState(null);
  const [caricandoAnteprima, setCaricandoAnteprima] = useState(false);

  useEffect(() => {
    loadIntegrations();
    loadRules();
    loadSegnalazioni();
    loadAzioniPendenti();
  }, []);

  function loadAzioniPendenti() {
    setCaricandoAzioni(true);
    api
      .get("/azioni-pendenti")
      .then((res) => setAzioniPendenti(res.data))
      .catch(() => setError("Impossibile caricare le azioni in attesa."))
      .finally(() => setCaricandoAzioni(false));
  }

  async function confermaAzione(id) {
    setConfermandoId(id);
    try {
      await api.post(`/azioni-pendenti/${id}/conferma`);
      setAzioniPendenti((prev) => prev.filter((a) => a.id !== id));
    } catch (err) {
      setError(err.response?.data?.detail ?? "Invio non riuscito.");
    } finally {
      setConfermandoId(null);
    }
  }

  async function rifiutaAzione(id) {
    try {
      await api.post(`/azioni-pendenti/${id}/rifiuta`);
      setAzioniPendenti((prev) => prev.filter((a) => a.id !== id));
    } catch {
      setError("Impossibile scartare l'azione.");
    }
  }

  function loadIntegrations() {
    api
      .get("/integrations")
      .then((res) => {
        const esplorabili = res.data.filter(
          (i) => i.kind === "database_external" || i.kind === "database_managed" || i.kind === "data_api"
        );
        setIntegrations(esplorabili);
        if (esplorabili.length > 0) setIntegrationId(esplorabili[0].id);
      })
      .catch(() => setError("Impossibile caricare le integrazioni."));
  }

  function loadRules() {
    api
      .get("/alerts")
      .then((res) => setRules(res.data))
      .catch(() => setError("Impossibile caricare le regole."));
  }

  function loadSegnalazioni() {
    setCaricandoSegnalazioni(true);
    api
      .get("/alerts/segnalazioni")
      .then((res) => setSegnalazioni(res.data))
      .catch(() => setError("Impossibile calcolare le segnalazioni."))
      .finally(() => setCaricandoSegnalazioni(false));
  }

  useEffect(() => {
    if (!integrationId) return;
    api
      .get(`/integrations/${integrationId}/tables`)
      .then((res) => {
        setError("");
        setTables(res.data.tables);
        setTableName(res.data.tables[0] ?? "");
      })
      .catch(() => setError("Impossibile leggere le tabelle di questa integrazione."));
  }, [integrationId]);

  useEffect(() => {
    if (!integrationId || !tableName) {
      setSchema([]);
      return;
    }
    api
      .get(`/integrations/${integrationId}/tables/${tableName}/schema`)
      .then((res) => {
        setError("");
        setSchema(res.data.columns);
        setConfig(configDefault(conditionType, res.data.columns));
        setAzioneToColonna(indovinaPerNome(res.data.columns.map((c) => c.name), INDIZI_EMAIL));
      })
      .catch(() => setError("Impossibile leggere lo schema della tabella."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [integrationId, tableName]);

  // La colonna obbligatoria per ciascun tipo — senza questa l'anteprima
  // fallirebbe con un errore poco utile invece di restare in silenzio finché
  // l'utente non ha ancora scelto una colonna.
  function criteriPronti(tipo, cfg) {
    if (tipo === "scadenza_superata") return Boolean(cfg.colonna_data);
    if (tipo === "soglia_numerica" || tipo === "valore_anomalo") return Boolean(cfg.colonna);
    return false;
  }

  useEffect(() => {
    if (!integrationId || !tableName || !criteriPronti(conditionType, config)) {
      setAnteprima(null);
      return;
    }
    setCaricandoAnteprima(true);
    const timeout = setTimeout(() => {
      api
        .post("/alerts/anteprima", {
          integration_id: integrationId,
          table_name: tableName,
          condition_type: conditionType,
          config,
        })
        .then((res) => setAnteprima(res.data))
        .catch(() => setAnteprima(null))
        .finally(() => setCaricandoAnteprima(false));
    }, 400); // debounce: non un'anteprima ad ogni singolo carattere digitato
    return () => clearTimeout(timeout);
  }, [integrationId, tableName, conditionType, config]);

  function cambiaTipo(nuovoTipo) {
    setConditionType(nuovoTipo);
    setConfig(configDefault(nuovoTipo, schema));
  }

  function aggiornaConfig(chiave, valore) {
    setConfig((prev) => ({ ...prev, [chiave]: valore }));
  }

  const colonneDisponibili = schema.map((c) => c.name);

  async function salvaRegola(e) {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      await api.post("/alerts", {
        integration_id: integrationId,
        table_name: tableName,
        name: name || tableName,
        condition_type: conditionType,
        config,
        messaggio_template: messaggioTemplate,
        azione_template: mostraAzione
          ? { to_colonna: azioneToColonna, oggetto_template: azioneOggetto, corpo_template: azioneCorpo }
          : {},
      });
      setName("");
      setMessaggioTemplate("");
      setMostraAzione(false);
      setAzioneOggetto("");
      setAzioneCorpo("");
      loadRules();
      loadSegnalazioni();
      loadAzioniPendenti();
    } catch (err) {
      setError(err.response?.data?.detail ?? "Impossibile salvare la regola.");
    } finally {
      setSaving(false);
    }
  }

  async function eliminaRegola(ruleId) {
    try {
      await api.delete(`/alerts/${ruleId}`);
      setRules((prev) => prev.filter((r) => r.id !== ruleId));
      loadSegnalazioni();
    } catch {
      setError("Impossibile eliminare la regola.");
    }
  }

  return (
    <div className="flex">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Topbar />
        <main className="p-6 flex-1 max-w-5xl space-y-8">
          <div className="flex items-center gap-2">
            <BellRing size={20} className="text-slate-400" aria-hidden="true" />
            <h1 className="text-lg font-semibold text-slate-800">Segnalazioni</h1>
          </div>
          <p className="text-sm text-slate-500 -mt-6">
            Configura una regola una volta e l'agente nota da solo quando scatta — una scadenza
            superata, un valore fuori soglia, un importo anomalo — senza che tu debba chiedere.
            Nessun LLM: regole matematiche verificabili, calcolate sui dati veri a ogni apertura.
          </p>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <section className="bg-white border border-slate-200 rounded-lg p-5 space-y-4">
            <h2 className="text-sm font-semibold text-slate-600">Nuova regola</h2>

            {integrations.length === 0 ? (
              <p className="text-sm text-slate-500">
                Nessuna sorgente dati collegata. Vai su Integrazioni per collegarne una.
              </p>
            ) : (
              <form onSubmit={salvaRegola} className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">Integrazione</label>
                    <select
                      value={integrationId ?? ""}
                      onChange={(e) => setIntegrationId(Number(e.target.value))}
                      className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                    >
                      {integrations.map((i) => (
                        <option key={i.id} value={i.id}>
                          {i.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">Tabella</label>
                    <select
                      value={tableName}
                      onChange={(e) => setTableName(e.target.value)}
                      className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                    >
                      {tables.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">Nome regola</label>
                    <input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder={tableName || "Nome"}
                      className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">Tipo di regola</label>
                    <select
                      value={conditionType}
                      onChange={(e) => cambiaTipo(e.target.value)}
                      className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                    >
                      {TIPI.map((t) => (
                        <option key={t.value} value={t.value}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {conditionType === "scadenza_superata" && (
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs text-slate-500 mb-1">Colonna data *</label>
                      <select
                        value={config.colonna_data ?? ""}
                        onChange={(e) => aggiornaConfig("colonna_data", e.target.value)}
                        required
                        className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                      >
                        <option value="">—</option>
                        {colonneDisponibili.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs text-slate-500 mb-1">
                        Giorni di tolleranza (0 = segnala appena passata)
                      </label>
                      <input
                        type="number"
                        value={config.giorni_tolleranza ?? 0}
                        onChange={(e) => aggiornaConfig("giorni_tolleranza", Number(e.target.value))}
                        className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                      />
                    </div>
                  </div>
                )}

                {conditionType === "soglia_numerica" && (
                  <div className="grid grid-cols-3 gap-4">
                    <div>
                      <label className="block text-xs text-slate-500 mb-1">Colonna numerica *</label>
                      <select
                        value={config.colonna ?? ""}
                        onChange={(e) => aggiornaConfig("colonna", e.target.value)}
                        required
                        className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                      >
                        <option value="">—</option>
                        {colonneDisponibili.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs text-slate-500 mb-1">Condizione</label>
                      <select
                        value={config.operatore ?? ">"}
                        onChange={(e) => aggiornaConfig("operatore", e.target.value)}
                        className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                      >
                        <option value=">">maggiore di</option>
                        <option value=">=">maggiore o uguale a</option>
                        <option value="<">minore di</option>
                        <option value="<=">minore o uguale a</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs text-slate-500 mb-1">Soglia</label>
                      <input
                        type="number"
                        step="any"
                        value={config.soglia ?? 0}
                        onChange={(e) => aggiornaConfig("soglia", Number(e.target.value))}
                        className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                      />
                    </div>
                  </div>
                )}

                {conditionType === "valore_anomalo" && (
                  <div className="grid grid-cols-3 gap-4">
                    <div>
                      <label className="block text-xs text-slate-500 mb-1">Colonna numerica *</label>
                      <select
                        value={config.colonna ?? ""}
                        onChange={(e) => aggiornaConfig("colonna", e.target.value)}
                        required
                        className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                      >
                        <option value="">—</option>
                        {colonneDisponibili.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs text-slate-500 mb-1">
                        Confronta dentro il gruppo (opzionale)
                      </label>
                      <select
                        value={config.colonna_gruppo ?? ""}
                        onChange={(e) => aggiornaConfig("colonna_gruppo", e.target.value)}
                        className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                      >
                        <option value="">— tutte le righe insieme —</option>
                        {colonneDisponibili.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs text-slate-500 mb-1">Deviazioni standard</label>
                      <input
                        type="number"
                        step="0.1"
                        value={config.soglia_deviazioni ?? 2}
                        onChange={(e) => aggiornaConfig("soglia_deviazioni", Number(e.target.value))}
                        className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                      />
                    </div>
                  </div>
                )}

                {caricandoAnteprima && (
                  <p className="text-xs text-slate-400">Calcolo quante righe scatterebbero ora...</p>
                )}
                {anteprima && !caricandoAnteprima && (
                  <div
                    className={`text-xs rounded-md px-3 py-2 border ${
                      anteprima.totale > 0
                        ? "bg-amber-50 text-amber-700 border-amber-200"
                        : "bg-slate-50 text-slate-500 border-slate-200"
                    }`}
                  >
                    {anteprima.totale === 0
                      ? "Con questi criteri, oggi non scatterebbe nessuna segnalazione."
                      : `Con questi criteri, oggi scatterebbero ${anteprima.totale} segnalazion${
                          anteprima.totale === 1 ? "e" : "i"
                        }${anteprima.esempi.length > 0 ? ": " + anteprima.esempi.join("; ") : ""}.`}
                  </div>
                )}

                <div>
                  <label className="block text-xs text-slate-500 mb-1">
                    Messaggio (opzionale) — lascialo vuoto per un messaggio generato automaticamente
                  </label>
                  <input
                    value={messaggioTemplate}
                    onChange={(e) => setMessaggioTemplate(e.target.value)}
                    placeholder="es. {{nome}} ha un pagamento scaduto di {{importo_dovuto}}"
                    className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                  />
                  <InserisciCampo
                    colonne={colonneDisponibili}
                    onInsert={(c) => setMessaggioTemplate((prev) => aggiungiSegnaposto(prev, c))}
                  />
                </div>

                <div className="border-t border-slate-100 pt-4">
                  {!mostraAzione ? (
                    <button
                      type="button"
                      onClick={() => setMostraAzione(true)}
                      className="flex items-center gap-1.5 text-xs font-medium text-slate-600 hover:text-slate-900"
                    >
                      <Mail size={13} aria-hidden="true" />
                      + Aggiungi un'azione automatica (es. un sollecito pronto da confermare)
                    </button>
                  ) : (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <p className="text-xs font-medium text-slate-600">
                          Quando questa regola scatta, prepara anche una bozza pronta (non inviata —
                          resta in attesa di conferma qui sotto)
                        </p>
                        <button
                          type="button"
                          onClick={() => setMostraAzione(false)}
                          className="text-xs text-slate-400 hover:text-red-600"
                        >
                          Rimuovi
                        </button>
                      </div>
                      <div>
                        <label className="block text-xs text-slate-500 mb-1">Colonna indirizzo email *</label>
                        <select
                          value={azioneToColonna}
                          onChange={(e) => setAzioneToColonna(e.target.value)}
                          required
                          className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                        >
                          <option value="">—</option>
                          {colonneDisponibili.map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs text-slate-500 mb-1">Oggetto</label>
                        <input
                          value={azioneOggetto}
                          onChange={(e) => setAzioneOggetto(e.target.value)}
                          placeholder="Sollecito pagamento"
                          className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                        />
                        <InserisciCampo
                          colonne={colonneDisponibili}
                          onInsert={(c) => setAzioneOggetto((prev) => aggiungiSegnaposto(prev, c))}
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-slate-500 mb-1">Testo</label>
                        <textarea
                          value={azioneCorpo}
                          onChange={(e) => setAzioneCorpo(e.target.value)}
                          rows={3}
                          placeholder="Gentile, le ricordiamo il pagamento di..."
                          className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                        />
                        <InserisciCampo
                          colonne={colonneDisponibili}
                          onInsert={(c) => setAzioneCorpo((prev) => aggiungiSegnaposto(prev, c))}
                        />
                      </div>
                    </div>
                  )}
                </div>

                {isAdmin ? (
                  <button
                    type="submit"
                    disabled={saving || !tableName}
                    className="px-4 py-2 rounded-md bg-slate-800 text-white text-sm font-medium disabled:opacity-50"
                  >
                    {saving ? "Salvataggio..." : "Salva regola"}
                  </button>
                ) : (
                  <p className="text-xs text-slate-500">
                    Sei in sola lettura: puoi provare l'anteprima ma non salvare una nuova regola.
                  </p>
                )}
              </form>
            )}
          </section>

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-600">
                Azioni pronte da confermare {azioniPendenti.length > 0 && `(${azioniPendenti.length})`}
              </h2>
              <button
                onClick={loadAzioniPendenti}
                disabled={caricandoAzioni}
                className="text-xs px-2 py-1 rounded-md bg-slate-100 text-slate-700 disabled:opacity-50"
              >
                {caricandoAzioni ? "Caricamento..." : "Aggiorna"}
              </button>
            </div>
            <p className="text-xs text-slate-400 -mt-2">
              Bozze che Cortex ha preparato da solo (es. un sollecito) quando una regola con
              un'azione collegata è scattata — non inviate finché non le confermi.
            </p>
            {azioniPendenti.length === 0 ? (
              <p className="text-sm text-slate-500">Nessuna azione in attesa al momento.</p>
            ) : (
              <ul className="space-y-2">
                {azioniPendenti.map((a) => (
                  <li key={a.id} className="bg-white border border-slate-200 rounded-lg p-3 space-y-2">
                    <div className="text-xs text-slate-400">{a.origine}</div>
                    <div className="text-sm text-slate-700">
                      <strong>A:</strong> {a.to_address}
                    </div>
                    <div className="text-sm text-slate-700">
                      <strong>Oggetto:</strong> {a.subject}
                    </div>
                    <div className="text-xs text-slate-500 whitespace-pre-wrap">{a.body}</div>
                    {isAdmin ? (
                      <div className="flex gap-2 pt-1">
                        <button
                          onClick={() => confermaAzione(a.id)}
                          disabled={confermandoId === a.id}
                          className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-emerald-600 text-white text-xs font-medium disabled:opacity-50"
                        >
                          <Check size={12} aria-hidden="true" />
                          {confermandoId === a.id ? "Invio..." : "Conferma e invia"}
                        </button>
                        <button
                          onClick={() => rifiutaAzione(a.id)}
                          className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-slate-100 text-slate-700 text-xs font-medium"
                        >
                          <X size={12} aria-hidden="true" />
                          Scarta
                        </button>
                      </div>
                    ) : (
                      <p className="text-xs text-slate-400">Solo un amministratore può confermare o scartare.</p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-600">Regole configurate</h2>
            {rules.length === 0 && <p className="text-sm text-slate-500">Nessuna regola configurata ancora.</p>}
            {rules.map((rule) => (
              <div
                key={rule.id}
                className="bg-white border border-slate-200 rounded-lg p-3 flex items-center justify-between"
              >
                <div>
                  <div className="text-sm font-medium text-slate-800">{rule.name}</div>
                  <div className="text-xs text-slate-400">
                    {TIPI.find((t) => t.value === rule.condition_type)?.label} — tabella {rule.table_name}
                  </div>
                </div>
                {isAdmin && (
                  <button
                    onClick={() => eliminaRegola(rule.id)}
                    aria-label="Elimina regola"
                    className="text-slate-400 hover:text-red-600 p-1"
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
            ))}
          </section>

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-600">
                Segnalazioni attive {segnalazioni.length > 0 && `(${segnalazioni.length})`}
              </h2>
              <button
                onClick={loadSegnalazioni}
                disabled={caricandoSegnalazioni}
                className="text-xs px-2 py-1 rounded-md bg-slate-100 text-slate-700 disabled:opacity-50"
              >
                {caricandoSegnalazioni ? "Calcolo..." : "Aggiorna"}
              </button>
            </div>
            {segnalazioni.length === 0 ? (
              <p className="text-sm text-slate-500">
                Nessuna segnalazione al momento — tutte le regole configurate sono rispettate.
              </p>
            ) : (
              <ul className="space-y-2">
                {segnalazioni.map((s, i) => (
                  <li
                    key={`${s.regola_id}-${s.pk}-${i}`}
                    className="bg-amber-50 border border-amber-200 rounded-lg p-3"
                  >
                    <div className="text-xs font-medium text-amber-700">{s.regola_nome}</div>
                    <div className="text-sm text-slate-700">{s.messaggio}</div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </main>
      </div>
    </div>
  );
}
