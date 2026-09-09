// Hub Integrazioni: collega credenziali esterne (Gmail, Stripe, DB/ERP, ...) o fai
// provisionare un database da Cortex per chi non ne ha ancora uno. I campi del
// form e i template dipendono dal catalogo del backend (GET /integrations/providers
// e /integrations/templates), non sono hardcodati qui: aggiungere un provider o un
// template nuovo è solo lavoro di backend.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Trash2, Plug, Database, ArrowRight, Pencil, Check, X } from "lucide-react";
import Sidebar from "../components/layout/Sidebar";
import Topbar from "../components/layout/Topbar";
import { useAuth } from "../context/AuthContext";
import api from "../services/api";

export default function Integrations() {
  const { user } = useAuth();
  // Collegare/scollegare credenziali esterne richiede un ruolo admin (vedi
  // backend/app/models/membership.py) — un utente sola lettura può comunque
  // vedere quali integrazioni esistono ed esplorarne i dati.
  const isAdmin = user?.role === "admin";
  const [providers, setProviders] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [integrations, setIntegrations] = useState([]);
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("");
  const [formValues, setFormValues] = useState({});
  const [template, setTemplate] = useState("blank");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Rinomina in linea: click sulla matita accanto al nome, senza una pagina
  // a parte — un'integrazione va rinominata al volo quando ci si accorge che
  // "custom_db #3" non dice nulla, non con una gita in un'altra schermata.
  const [renamingId, setRenamingId] = useState(null);
  const [renameValue, setRenameValue] = useState("");

  useEffect(() => {
    loadAll();
  }, []);

  async function loadAll() {
    setLoading(true);
    try {
      const [providersRes, templatesRes, integrationsRes] = await Promise.all([
        api.get("/integrations/providers"),
        api.get("/integrations/templates"),
        api.get("/integrations"),
      ]);
      setProviders(providersRes.data);
      setTemplates(templatesRes.data);
      setIntegrations(integrationsRes.data);
      if (providersRes.data.length > 0) {
        selectProvider(providersRes.data[0]);
      }
    } catch {
      setError("Impossibile caricare le integrazioni al momento.");
    } finally {
      setLoading(false);
    }
  }

  function selectProvider(entry) {
    setProvider(entry.provider);
    const defaults = {};
    for (const field of entry.fields) {
      defaults[field.key] = field.default ?? "";
    }
    setFormValues(defaults);
  }

  function handleProviderChange(e) {
    const entry = providers.find((p) => p.provider === e.target.value);
    if (entry) selectProvider(entry);
  }

  function handleFieldChange(key, value) {
    setFormValues((prev) => ({ ...prev, [key]: value }));
  }

  const currentProviderEntry = providers.find((p) => p.provider === provider);
  const isManaged = currentProviderEntry?.kind === "database_managed";
  // "data_api" (es. provider "rest_api") è esplorabile come un database: la
  // stessa icona/link "Esplora dati", solo la sorgente sotto è un'API REST
  // invece di SQL (vedi app.services.data_source sul backend).
  const isDatabaseKind = (kind) => kind === "database_external" || kind === "database_managed" || kind === "data_api";

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setNotice("");
    if (!name.trim()) {
      setError("Dai un nome all'integrazione: aiuta a distinguerla dalle altre in Viste e Segnalazioni.");
      return;
    }
    setSaving(true);
    try {
      if (isManaged) {
        await api.post("/integrations/provision", { name: name.trim(), template });
        setNotice("Database creato: lo trovi in \"Dati\" nel menu.");
      } else {
        await api.post("/integrations", { name: name.trim(), provider, credentials: formValues });
        setNotice("Integrazione salvata: le credenziali sono cifrate nel database.");
      }
      setName("");
      await loadAll();
    } catch {
      setError(
        isManaged
          ? "Impossibile creare il database al momento."
          : "Impossibile salvare l'integrazione. Controlla i campi inseriti."
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id) {
    setError("");
    setNotice("");
    try {
      await api.delete(`/integrations/${id}`);
      setIntegrations((prev) => prev.filter((i) => i.id !== id));
    } catch {
      setError("Impossibile rimuovere l'integrazione.");
    }
  }

  function iniziaRinomina(integration) {
    setRenamingId(integration.id);
    setRenameValue(integration.name);
  }

  async function salvaRinomina(id) {
    if (!renameValue.trim()) return;
    try {
      const { data } = await api.put(`/integrations/${id}`, { name: renameValue.trim() });
      setIntegrations((prev) => prev.map((i) => (i.id === id ? data : i)));
      setRenamingId(null);
    } catch {
      setError("Impossibile rinominare l'integrazione.");
    }
  }

  const currentFields = currentProviderEntry?.fields ?? [];

  return (
    <div className="flex">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Topbar />
        <main className="p-6 flex-1 grid grid-cols-1 lg:grid-cols-2 gap-6 max-w-4xl">
          <section>
            <h1 className="text-lg font-semibold text-slate-800 mb-6">Integrazioni collegate</h1>

            {loading && <p className="text-sm text-slate-500">Caricamento...</p>}
            {!loading && integrations.length === 0 && (
              <p className="text-sm text-slate-500">Nessuna integrazione collegata ancora.</p>
            )}

            <ul className="space-y-3">
              {integrations.map((integration) => (
                <li
                  key={integration.id}
                  className="bg-white border border-slate-200 rounded-lg p-4 flex items-start justify-between gap-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 min-w-0">
                      {isDatabaseKind(integration.kind) ? (
                        <Database size={16} className="text-slate-400 shrink-0" aria-hidden="true" />
                      ) : (
                        <Plug size={16} className="text-slate-400 shrink-0" aria-hidden="true" />
                      )}
                      {renamingId === integration.id ? (
                        <>
                          <input
                            value={renameValue}
                            onChange={(e) => setRenameValue(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && salvaRinomina(integration.id)}
                            autoFocus
                            className="min-w-0 flex-1 border border-slate-300 rounded-md px-2 py-0.5 text-sm font-medium"
                          />
                          <button
                            onClick={() => salvaRinomina(integration.id)}
                            aria-label="Salva nome"
                            className="text-emerald-600 hover:text-emerald-800 p-1 shrink-0"
                          >
                            <Check size={14} />
                          </button>
                          <button
                            onClick={() => setRenamingId(null)}
                            aria-label="Annulla"
                            className="text-slate-400 hover:text-slate-600 p-1 shrink-0"
                          >
                            <X size={14} />
                          </button>
                        </>
                      ) : (
                        <>
                          <span className="font-medium text-slate-800 truncate">{integration.name}</span>
                          {isAdmin && (
                            <button
                              onClick={() => iniziaRinomina(integration)}
                              aria-label="Rinomina integrazione"
                              className="text-slate-300 hover:text-slate-600 p-1 shrink-0"
                            >
                              <Pencil size={12} />
                            </button>
                          )}
                        </>
                      )}
                      <span
                        className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${
                          integration.status === "connected"
                            ? "bg-emerald-100 text-emerald-700"
                            : "bg-amber-100 text-amber-700"
                        }`}
                      >
                        {integration.status}
                      </span>
                    </div>
                    <div className="text-xs text-slate-400 mt-0.5">{integration.provider}</div>
                    <dl className="mt-2 space-y-1 text-xs text-slate-500">
                      {Object.entries(integration.credentials_preview).map(([key, value]) => (
                        <div key={key} className="flex gap-2 min-w-0">
                          <dt className="font-mono shrink-0">{key}:</dt>
                          <dd className="font-mono truncate" title={value}>{value}</dd>
                        </div>
                      ))}
                    </dl>
                    {isDatabaseKind(integration.kind) && (
                      <Link
                        to="/data"
                        className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-slate-700 hover:text-slate-900"
                      >
                        Esplora dati <ArrowRight size={12} />
                      </Link>
                    )}
                  </div>
                  {isAdmin && (
                    <button
                      onClick={() => handleDelete(integration.id)}
                      aria-label="Rimuovi integrazione"
                      className="text-slate-400 hover:text-red-600 p-1"
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>

          {!isAdmin && (
            <p className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-lg p-4">
              Sei in sola lettura: puoi vedere le integrazioni collegate ma non aggiungerne, rinominarle o
              rimuoverle. Chiedi a un amministratore di promuoverti dalla pagina Team se ti serve.
            </p>
          )}

          {isAdmin && (
          <section>
            <h2 className="text-lg font-semibold text-slate-800 mb-6">Aggiungi integrazione</h2>

            <form onSubmit={handleSubmit} className="bg-white border border-slate-200 rounded-lg p-6 space-y-4">
              <div>
                <label className="block text-sm text-slate-600 mb-1">Nome *</label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Es. Database Sampeyre, API Portale annunci"
                  required
                  className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                />
                <p className="text-xs text-slate-400 mt-1">
                  Come la vedrai qui e nei menu di Viste e Segnalazioni — un nome tuo, non il nome del
                  provider.
                </p>
              </div>

              <div>
                <label className="block text-sm text-slate-600 mb-1">Servizio</label>
                <select
                  value={provider}
                  onChange={handleProviderChange}
                  className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                >
                  {providers.map((p) => (
                    <option key={p.provider} value={p.provider}>
                      {p.label ?? p.provider}
                    </option>
                  ))}
                </select>
                {currentProviderEntry?.description && (
                  <p className="text-xs text-slate-500 mt-1">{currentProviderEntry.description}</p>
                )}
              </div>

              {isManaged ? (
                <div>
                  <label className="block text-sm text-slate-600 mb-1">Struttura di partenza</label>
                  <select
                    value={template}
                    onChange={(e) => setTemplate(e.target.value)}
                    className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                  >
                    {templates.map((t) => (
                      <option key={t.template} value={t.template}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                  <p className="text-xs text-slate-500 mt-1">
                    {templates.find((t) => t.template === template)?.description}
                  </p>
                </div>
              ) : (
                currentFields.map((field) => (
                  <div key={field.key}>
                    <label className="block text-sm text-slate-600 mb-1">{field.label}</label>
                    <input
                      type={field.secret ? "password" : "text"}
                      value={formValues[field.key] ?? ""}
                      onChange={(e) => handleFieldChange(field.key, e.target.value)}
                      required={field.required !== false}
                      className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
                    />
                  </div>
                ))
              )}

              {error && <p className="text-sm text-red-600">{error}</p>}
              {notice && <p className="text-sm text-emerald-600">{notice}</p>}

              <button
                type="submit"
                disabled={saving || !provider || !name.trim()}
                className="w-full bg-slate-800 text-white rounded-md py-2 text-sm font-medium disabled:opacity-50"
              >
                {saving ? "Salvataggio..." : isManaged ? "Crea database" : "Salva integrazione"}
              </button>
            </form>
          </section>
          )}
        </main>
      </div>
    </div>
  );
}
