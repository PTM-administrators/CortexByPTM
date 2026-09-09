// Viste salvate: configura una volta come mostrare una tabella collegata (a
// schede, a calendario, o a tabella con azioni per riga) e riusala — senza
// che serva scrivere codice per ogni settore. Generica per qualunque azienda:
// un immobiliare mappa "titolo/sottotitolo" sui suoi annunci per vederli a
// schede, un barbiere mappa "data/titolo" sui suoi appuntamenti per un
// calendario, un'azienda qualunque aggiunge un bottone email su una tabella
// di debitori.
import { useEffect, useMemo, useState } from "react";
import { Download, LayoutTemplate, Plus, Trash2, X } from "lucide-react";
import Sidebar from "../components/layout/Sidebar";
import Topbar from "../components/layout/Topbar";
import InserisciCampo from "../components/ui/InserisciCampo";
import WidgetCanvas from "../components/widgets/WidgetCanvas";
import { useAuth } from "../context/AuthContext";
import api, { scaricaFile } from "../services/api";

// Aggiunge {{colonna}} in coda al testo attuale invece di richiedere che
// l'utente sappia scrivere la sintassi a mano (vedi InserisciCampo).
function aggiungiSegnaposto(valoreAttuale, colonna) {
  return `${valoreAttuale}${valoreAttuale ? " " : ""}{{${colonna}}}`;
}

const MODI = [
  { value: "table", label: "Tabella (con azioni opzionali per riga)" },
  { value: "cards", label: "Schede" },
  { value: "calendar", label: "Calendario" },
];

// Parole-chiave per indovinare a quale ruolo (titolo/sottotitolo/badge/data/
// email) corrisponde una colonna, guardando solo il suo nome. Non è mai
// certo — solo un punto di partenza sensato al posto di "—": l'utente vede
// subito qualcosa di plausibile e lo corregge se serve, invece di dover
// capire da zero cosa significa ogni ruolo.
const INDIZI_RUOLO = {
  titolo: ["titolo", "nome", "name", "title", "oggetto", "descrizione_breve"],
  sottotitolo: ["prezzo", "importo", "amount", "price", "descrizione", "note"],
  badge: ["stato", "status", "tipo", "categoria", "category", "badge"],
  data: ["data", "date", "scadenza", "giorno", "quando", "appuntamento"],
  email: ["email", "mail", "posta"],
};

function indovinaColonna(colonne, ruolo) {
  const parole = INDIZI_RUOLO[ruolo] ?? [];
  for (const parola of parole) {
    const trovata = colonne.find((c) => c.toLowerCase().includes(parola));
    if (trovata) return trovata;
  }
  return "";
}

function indovinaMapping(colonne, ruoli) {
  const risultato = {};
  for (const ruolo of ruoli) {
    risultato[ruolo] = indovinaColonna(colonne, ruolo);
  }
  return risultato;
}

function nuovaAzione(colonneDisponibili = []) {
  return {
    nome: "Sollecito",
    to_colonna: indovinaColonna(colonneDisponibili, "email"),
    oggetto_template: "",
    corpo_template: "",
  };
}

// Sostituzione {{colonna}} -> valore reale, identica a quella del backend
// (app/api/views.py._render_template): serve solo per mostrare un'anteprima,
// l'invio vero resta sempre calcolato dal server.
function applicaTemplate(testo, riga) {
  if (!riga) return testo;
  return testo.replace(/\{\{(.*?)\}\}/g, (_, chiave) => {
    const k = chiave.trim();
    return k in riga ? String(riga[k] ?? "") : `{{${k}}}`;
  });
}

// Costruisce lo stesso tipo di spec di view_rendering.py ma sul client, con
// le righe di esempio già caricate: l'anteprima si aggiorna a ogni modifica
// del mapping, senza bisogno di salvare la vista per vedere cosa produce.
function costruisciAnteprima(mode, mapping, sampleRows, primaryKey, titolo) {
  if (!sampleRows || sampleRows.length === 0) return null;
  if (mode === "cards") {
    return {
      type: "entity_cards",
      title: titolo || "Anteprima",
      primary_key: primaryKey,
      items: sampleRows.map((r) => ({
        _pk: r[primaryKey],
        titolo: r[mapping.titolo] ?? "",
        sottotitolo: mapping.sottotitolo ? r[mapping.sottotitolo] : undefined,
        badge: mapping.badge ? r[mapping.badge] : undefined,
      })),
    };
  }
  if (mode === "calendar") {
    return {
      type: "calendar",
      title: titolo || "Anteprima",
      events: sampleRows
        .filter((r) => mapping.data && r[mapping.data])
        .map((r) => ({ data: String(r[mapping.data]).slice(0, 10), titolo: r[mapping.titolo] ?? "" })),
    };
  }
  if (mode === "table") {
    return {
      type: "table",
      title: titolo || "Anteprima",
      columns: Object.keys(sampleRows[0]).map((k) => ({ key: k, label: k })),
      rows: sampleRows,
      primary_key: primaryKey,
      actions: [],
    };
  }
  return null;
}

export default function Viste() {
  const { user } = useAuth();
  // Creare/eliminare Viste richiede un ruolo admin (vedi
  // backend/app/models/membership.py) — vederle e usarle resta aperto a tutti.
  const isAdmin = user?.role === "admin";
  const [integrations, setIntegrations] = useState([]);
  const [views, setViews] = useState([]);
  const [viewData, setViewData] = useState({}); // { [viewId]: spec }
  const [error, setError] = useState("");

  // Modelli pronti (solo profilo Arca): stessa idea delle Viste ma senza
  // configuratore — Cortex già conosce lo schema Arca standard, quindi
  // costruisce la vista da solo invece di far scegliere tabella/colonne tra
  // 380 possibili (vedi PLAN.md, punto 3 del feedback dell'utente). Non
  // salvati: ricalcolati al volo ad ogni click, come i widget della chat.
  const [profiloIntegrazione, setProfiloIntegrazione] = useState(null);
  const [modelloAttivo, setModelloAttivo] = useState(null); // "clienti-scoperti" | "fornitori-da-pagare"
  const [modelloWidget, setModelloWidget] = useState(null);
  const [caricandoModello, setCaricandoModello] = useState(false);

  // Form di creazione
  const [integrationId, setIntegrationId] = useState(null);
  const [tables, setTables] = useState([]);
  const [tableName, setTableName] = useState("");
  const [schema, setSchema] = useState([]);
  const [sampleRows, setSampleRows] = useState([]);
  const [primaryKey, setPrimaryKey] = useState(null);
  const [mode, setMode] = useState("table");
  const [name, setName] = useState("");
  const [mapping, setMapping] = useState({});
  const [actions, setActions] = useState([]);
  const [saving, setSaving] = useState(false);

  // Conferma azione riga
  const [pendingRowAction, setPendingRowAction] = useState(null); // {id, preview}
  const [confirming, setConfirming] = useState(false);
  const [rowActionNotice, setRowActionNotice] = useState("");

  useEffect(() => {
    loadIntegrations();
    loadViews();
  }, []);

  function loadIntegrations() {
    api
      .get("/integrations")
      .then((res) => {
        // "data_api" (es. provider "rest_api") è esplorabile come un
        // database: stessa configurazione di vista, la sorgente sotto è
        // un'API REST invece di SQL (vedi app.services.data_source).
        const dbIntegrations = res.data.filter(
          (i) => i.kind === "database_external" || i.kind === "database_managed" || i.kind === "data_api"
        );
        setIntegrations(dbIntegrations);
        if (dbIntegrations.length > 0) setIntegrationId(dbIntegrations[0].id);
      })
      .catch(() => setError("Impossibile caricare le integrazioni."));
  }

  function loadViews() {
    api
      .get("/views")
      .then((res) => {
        setViews(res.data);
        res.data.forEach(loadViewData);
      })
      .catch(() => setError("Impossibile caricare le viste salvate."));
  }

  function loadViewData(view) {
    api
      .get(`/views/${view.id}/data`)
      .then((res) => setViewData((prev) => ({ ...prev, [view.id]: res.data })))
      .catch(() => setViewData((prev) => ({ ...prev, [view.id]: null })));
  }

  useEffect(() => {
    setProfiloIntegrazione(null);
    setModelloAttivo(null);
    setModelloWidget(null);
    if (!integrationId) return;
    api
      .get(`/integrations/${integrationId}/accounting/profilo`)
      .then((res) => setProfiloIntegrazione(res.data.profilo))
      .catch(() => setProfiloIntegrazione(null)); // integrazione senza motore contabile: nessun modello pronto, non un errore da mostrare
  }, [integrationId]);

  function apriModello(modello) {
    setModelloAttivo(modello);
    setModelloWidget(null);
    setCaricandoModello(true);
    setError("");
    api
      .get(`/integrations/${integrationId}/accounting/modelli/${modello}`)
      .then((res) => setModelloWidget(res.data))
      .catch((err) => setError(err.response?.data?.detail ?? "Impossibile calcolare questo modello."))
      .finally(() => setCaricandoModello(false));
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
      setSampleRows([]);
      setPrimaryKey(null);
      return;
    }
    api
      .get(`/integrations/${integrationId}/tables/${tableName}/schema`)
      .then((res) => {
        setError("");
        setSchema(res.data.columns);
        const colonne = res.data.columns.map((c) => c.name);
        // Suggerimento di partenza, non definitivo: l'utente lo vede subito
        // nell'anteprima e lo cambia dai menu se non è quello giusto.
        setMapping(indovinaMapping(colonne, ["titolo", "sottotitolo", "badge", "data"]));
      })
      .catch(() => setError("Impossibile leggere lo schema della tabella."));
    api
      .get(`/integrations/${integrationId}/tables/${tableName}/rows`, { params: { limit: 5 } })
      .then((res) => {
        setSampleRows(res.data.rows);
        setPrimaryKey(res.data.primary_key);
      })
      .catch(() => setSampleRows([]));
  }, [integrationId, tableName]);

  const anteprima = useMemo(
    () => costruisciAnteprima(mode, mapping, sampleRows, primaryKey, name || tableName),
    [mode, mapping, sampleRows, primaryKey, name, tableName]
  );

  function aggiungiAzione() {
    setActions((prev) => [...prev, nuovaAzione(colonneDisponibili)]);
  }

  function aggiornaAzione(index, campo, valore) {
    setActions((prev) => prev.map((a, i) => (i === index ? { ...a, [campo]: valore } : a)));
  }

  function rimuoviAzione(index) {
    setActions((prev) => prev.filter((_, i) => i !== index));
  }

  async function salvaVista(e) {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      await api.post("/views", {
        integration_id: integrationId,
        table_name: tableName,
        name: name || tableName,
        mode,
        column_mapping: mode === "table" ? {} : mapping,
        row_actions: mode === "table" ? actions : [],
      });
      setName("");
      setMapping({});
      setActions([]);
      loadViews();
    } catch (err) {
      setError(err.response?.data?.detail ?? "Impossibile salvare la vista.");
    } finally {
      setSaving(false);
    }
  }

  async function eliminaVista(viewId) {
    try {
      await api.delete(`/views/${viewId}`);
      setViews((prev) => prev.filter((v) => v.id !== viewId));
    } catch {
      setError("Impossibile eliminare la vista.");
    }
  }

  async function handleRowAction(viewId, pkValue, actionIndex) {
    setError("");
    setRowActionNotice("");
    try {
      const { data } = await api.post(`/views/${viewId}/rows/${pkValue}/actions/${actionIndex}`);
      setPendingRowAction({ viewId, id: data.id, preview: data.preview });
    } catch (err) {
      setError(err.response?.data?.detail ?? "Impossibile preparare l'azione.");
    }
  }

  async function confermaRowAction() {
    setConfirming(true);
    try {
      const { data } = await api.post(`/agent/confirm/${pendingRowAction.id}`);
      setRowActionNotice(`Inviata a ${data.detail?.to ?? ""}.`);
      setPendingRowAction(null);
    } catch (err) {
      setRowActionNotice(err.response?.data?.detail ?? "Invio non riuscito.");
    } finally {
      setConfirming(false);
    }
  }

  const colonneDisponibili = schema.map((c) => c.name);

  return (
    <div className="flex">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Topbar />
        <main className="p-6 flex-1 max-w-5xl space-y-8">
          <div className="flex items-center gap-2">
            <LayoutTemplate size={20} className="text-slate-400" aria-hidden="true" />
            <h1 className="text-lg font-semibold text-slate-800">Viste</h1>
          </div>
          <p className="text-sm text-slate-500 -mt-6">
            Configura una volta come vedere una tua tabella collegata — a schede, a calendario, o a
            tabella con azioni — e riusala. Nessun codice per ogni nuovo settore.
          </p>

          {error && <p className="text-sm text-red-600">{error}</p>}

          {integrations.length > 0 && (
            <section className="bg-white border border-slate-200 rounded-lg p-5 space-y-4">
              <div>
                <h2 className="text-sm font-semibold text-slate-600">Modelli pronti</h2>
                <p className="text-xs text-slate-400 mt-1">
                  Per un database gestionale (Arca) Cortex conosce già lo schema: nessuna tabella o
                  colonna da scegliere, clicca e vedi subito il risultato.
                </p>
              </div>

              <div>
                <label className="block text-xs text-slate-500 mb-1">Integrazione</label>
                <select
                  value={integrationId ?? ""}
                  onChange={(e) => setIntegrationId(Number(e.target.value))}
                  className="w-full max-w-xs border border-slate-300 rounded-md px-3 py-2 text-sm"
                >
                  {integrations.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name}
                    </option>
                  ))}
                </select>
              </div>

              {profiloIntegrazione === "arca" ? (
                <>
                  <div className="flex gap-3">
                    <button
                      onClick={() => apriModello("fornitori-da-pagare")}
                      className={`px-3 py-2 rounded-md text-sm font-medium border ${
                        modelloAttivo === "fornitori-da-pagare"
                          ? "bg-slate-800 text-white border-slate-800"
                          : "bg-white text-slate-700 border-slate-300 hover:border-slate-400"
                      }`}
                    >
                      Fornitori da pagare
                    </button>
                    <button
                      onClick={() => apriModello("clienti-scoperti")}
                      className={`px-3 py-2 rounded-md text-sm font-medium border ${
                        modelloAttivo === "clienti-scoperti"
                          ? "bg-slate-800 text-white border-slate-800"
                          : "bg-white text-slate-700 border-slate-300 hover:border-slate-400"
                      }`}
                    >
                      Clienti con saldo scoperto
                    </button>
                  </div>

                  {caricandoModello && <p className="text-sm text-slate-500">Calcolo in corso...</p>}

                  {modelloWidget && !caricandoModello && (
                    <div className="space-y-2">
                      <WidgetCanvas spec={modelloWidget} placeholder="Nessun risultato." onRowAction={() => {}} />
                      {modelloWidget.rows.length > 0 && (
                        <p className="text-sm font-medium text-slate-700">
                          Totale: {new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(modelloWidget.totale)}
                        </p>
                      )}
                      <p className="text-xs text-slate-400">{modelloWidget.nota}</p>
                    </div>
                  )}
                </>
              ) : (
                <p className="text-sm text-slate-500">
                  Nessun modello pronto per questa integrazione — usa il configuratore qui sotto.
                </p>
              )}
            </section>
          )}

          <section className="bg-white border border-slate-200 rounded-lg p-5 space-y-4">
            <h2 className="text-sm font-semibold text-slate-600">Nuova vista</h2>

            {integrations.length === 0 ? (
              <p className="text-sm text-slate-500">
                Nessun database collegato. Vai su Integrazioni per collegarne uno.
              </p>
            ) : (
              <form onSubmit={salvaVista} className="space-y-4">
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
                    <label className="block text-xs text-slate-500 mb-1">Nome vista</label>
                    <input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder={tableName || "Nome"}
                      className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">Modalità</label>
                    <select
                      value={mode}
                      onChange={(e) => setMode(e.target.value)}
                      className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                    >
                      {MODI.map((m) => (
                        <option key={m.value} value={m.value}>
                          {m.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {mode === "cards" && (
                  <div className="grid grid-cols-3 gap-4">
                    {["titolo", "sottotitolo", "badge"].map((ruolo) => (
                      <div key={ruolo}>
                        <label className="block text-xs text-slate-500 mb-1 capitalize">
                          {ruolo}
                          {ruolo === "titolo" && " *"}
                        </label>
                        <select
                          value={mapping[ruolo] ?? ""}
                          onChange={(e) => setMapping((prev) => ({ ...prev, [ruolo]: e.target.value }))}
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
                    ))}
                  </div>
                )}

                {mode === "calendar" && (
                  <div className="grid grid-cols-2 gap-4">
                    {["data", "titolo"].map((ruolo) => (
                      <div key={ruolo}>
                        <label className="block text-xs text-slate-500 mb-1 capitalize">{ruolo} *</label>
                        <select
                          value={mapping[ruolo] ?? ""}
                          onChange={(e) => setMapping((prev) => ({ ...prev, [ruolo]: e.target.value }))}
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
                    ))}
                  </div>
                )}

                {(mode === "cards" || mode === "calendar") && (
                  <div>
                    <p className="text-xs text-slate-500 mb-2">
                      Anteprima con {sampleRows.length || 0} righe reali — i mapping sono già stati
                      indovinati dal nome delle colonne, correggili qui sotto se serve.
                    </p>
                    <div className="bg-slate-50 border border-dashed border-slate-300 rounded-lg p-3">
                      <WidgetCanvas
                        spec={anteprima}
                        placeholder="Nessuna riga da mostrare in anteprima."
                        onRowAction={() => {}}
                      />
                    </div>
                  </div>
                )}

                {mode === "table" && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <label className="text-xs text-slate-500">
                        Azioni per riga (opzionali) — clicca su una colonna sotto Oggetto/Testo per
                        personalizzarlo con i valori della riga
                      </label>
                      <button
                        type="button"
                        onClick={aggiungiAzione}
                        className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-slate-100 text-slate-700"
                      >
                        <Plus size={12} /> Aggiungi azione
                      </button>
                    </div>
                    {actions.map((a, i) => (
                      <div key={i} className="border border-slate-200 rounded-md p-3 space-y-2 relative">
                        <button
                          type="button"
                          onClick={() => rimuoviAzione(i)}
                          aria-label="Rimuovi azione"
                          className="absolute top-2 right-2 text-slate-400 hover:text-red-600"
                        >
                          <X size={14} />
                        </button>
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="block text-xs text-slate-500 mb-1">Nome bottone</label>
                            <input
                              value={a.nome}
                              onChange={(e) => aggiornaAzione(i, "nome", e.target.value)}
                              className="w-full border border-slate-300 rounded-md px-2 py-1.5 text-sm"
                            />
                          </div>
                          <div>
                            <label className="block text-xs text-slate-500 mb-1">Colonna email destinatario</label>
                            <select
                              value={a.to_colonna}
                              onChange={(e) => aggiornaAzione(i, "to_colonna", e.target.value)}
                              className="w-full border border-slate-300 rounded-md px-2 py-1.5 text-sm"
                            >
                              <option value="">—</option>
                              {colonneDisponibili.map((c) => (
                                <option key={c} value={c}>
                                  {c}
                                </option>
                              ))}
                            </select>
                          </div>
                        </div>
                        <div>
                          <label className="block text-xs text-slate-500 mb-1">Oggetto</label>
                          <input
                            value={a.oggetto_template}
                            onChange={(e) => aggiornaAzione(i, "oggetto_template", e.target.value)}
                            placeholder="Sollecito pagamento"
                            className="w-full border border-slate-300 rounded-md px-2 py-1.5 text-sm"
                          />
                          <InserisciCampo
                            colonne={colonneDisponibili}
                            onInsert={(c) => aggiornaAzione(i, "oggetto_template", aggiungiSegnaposto(a.oggetto_template, c))}
                          />
                        </div>
                        <div>
                          <label className="block text-xs text-slate-500 mb-1">Testo</label>
                          <textarea
                            value={a.corpo_template}
                            onChange={(e) => aggiornaAzione(i, "corpo_template", e.target.value)}
                            placeholder="Gentile, le ricordiamo il pagamento di..."
                            rows={2}
                            className="w-full border border-slate-300 rounded-md px-2 py-1.5 text-sm"
                          />
                          <InserisciCampo
                            colonne={colonneDisponibili}
                            onInsert={(c) => aggiornaAzione(i, "corpo_template", aggiungiSegnaposto(a.corpo_template, c))}
                          />
                        </div>
                        {sampleRows.length > 0 && (a.oggetto_template || a.corpo_template) && (
                          <div className="bg-slate-50 border border-dashed border-slate-300 rounded-md p-2 text-xs text-slate-600 space-y-1">
                            <p className="text-slate-400">Anteprima sulla prima riga reale:</p>
                            <div>
                              <strong>Oggetto:</strong> {applicaTemplate(a.oggetto_template, sampleRows[0])}
                            </div>
                            <div>
                              <strong>Testo:</strong> {applicaTemplate(a.corpo_template, sampleRows[0])}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {isAdmin ? (
                  <button
                    type="submit"
                    disabled={saving || !tableName}
                    className="px-4 py-2 rounded-md bg-slate-800 text-white text-sm font-medium disabled:opacity-50"
                  >
                    {saving ? "Salvataggio..." : "Salva vista"}
                  </button>
                ) : (
                  <p className="text-xs text-slate-500">Sei in sola lettura: non puoi salvare una nuova vista.</p>
                )}
              </form>
            )}
          </section>

          {pendingRowAction && (
            <section className="bg-white border border-amber-300 rounded-lg p-4 space-y-2">
              <h3 className="text-sm font-semibold text-slate-700">Conferma invio</h3>
              <div className="text-xs text-slate-600 space-y-1">
                <div>
                  <strong>A:</strong> {pendingRowAction.preview.to_address}
                </div>
                <div>
                  <strong>Oggetto:</strong> {pendingRowAction.preview.subject}
                </div>
                <div>
                  <strong>Testo:</strong> {pendingRowAction.preview.body}
                </div>
              </div>
              <div className="flex gap-2 pt-1">
                <button
                  onClick={confermaRowAction}
                  disabled={confirming}
                  className="px-3 py-1.5 rounded-md bg-emerald-600 text-white text-xs font-medium disabled:opacity-50"
                >
                  {confirming ? "Invio..." : "Conferma invio"}
                </button>
                <button
                  onClick={() => setPendingRowAction(null)}
                  className="px-3 py-1.5 rounded-md bg-slate-200 text-slate-700 text-xs font-medium"
                >
                  Annulla
                </button>
              </div>
            </section>
          )}
          {rowActionNotice && <p className="text-sm text-emerald-700">{rowActionNotice}</p>}

          <section className="space-y-4">
            <h2 className="text-sm font-semibold text-slate-600">Viste salvate</h2>
            {views.length === 0 && <p className="text-sm text-slate-500">Nessuna vista salvata ancora.</p>}
            {views.map((view) => (
              <div key={view.id} className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-400">{view.table_name}</span>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => scaricaFile(`/views/${view.id}/export.xlsx`, `${view.name}.xlsx`)}
                      className="flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800"
                    >
                      <Download size={12} /> Esporta Excel
                    </button>
                    {isAdmin && (
                      <button
                        onClick={() => eliminaVista(view.id)}
                        aria-label="Elimina vista"
                        className="text-slate-400 hover:text-red-600"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </div>
                <WidgetCanvas
                  spec={viewData[view.id]}
                  placeholder="Caricamento..."
                  onRowAction={(pk, actionIndex) => handleRowAction(view.id, pk, actionIndex)}
                />
              </div>
            ))}
          </section>
        </main>
      </div>
    </div>
  );
}
