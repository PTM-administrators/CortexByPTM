// Esploratore dati generico: qualunque integrazione di tipo database (esterna o
// gestita da Cortex) si esplora da qui — stessa pagina per ogni settore. Sampeyre
// userà questa schermata per Movimenti/Cespiti, un'azienda e-commerce per il suo
// ERP: nessun codice qui è specifico di un singolo tenant o settore.
import { useEffect, useState } from "react";
import { Database, Plus, Pencil, Trash2, ChevronLeft, ChevronRight, X, Download, Upload } from "lucide-react";
import Sidebar from "../components/layout/Sidebar";
import Topbar from "../components/layout/Topbar";
import { useAuth } from "../context/AuthContext";
import api, { scaricaFile } from "../services/api";

const PAGE_SIZE = 25;

// Sceglie il tipo di <input> più adatto in base al tipo SQL riportato dalla
// reflection SQLAlchemy (es. "VARCHAR(255)", "NUMERIC(12, 2)", "DATE", "BOOLEAN").
function inputTypeFor(sqlType) {
  const t = sqlType.toUpperCase();
  if (t.includes("BOOL")) return "checkbox";
  if (t.includes("DATETIME") || t.includes("TIMESTAMP")) return "datetime-local";
  if (t.includes("DATE")) return "date";
  if (t.includes("INT") || t.includes("NUMERIC") || t.includes("DECIMAL") || t.includes("FLOAT") || t.includes("REAL"))
    return "number";
  return "text";
}

export default function DataExplorer() {
  const { user } = useAuth();
  // Scrivere sui dati collegati (righe, import) richiede un ruolo admin
  // (vedi backend/app/models/membership.py, già applicato lato backend) —
  // qui solo nasconde i controlli in anticipo invece di far scoprire il 403
  // dopo il click. L'anteprima di un import resta aperta a tutti: non scrive
  // nulla (stesso principio già in uso in Segnalazioni).
  const isAdmin = user?.role === "admin";
  const [integrations, setIntegrations] = useState([]);
  const [integrationId, setIntegrationId] = useState(null);
  const [tables, setTables] = useState([]);
  const [tableName, setTableName] = useState(null);
  const [schema, setSchema] = useState([]);
  const [rowsData, setRowsData] = useState({ columns: [], primary_key: null, rows: [], total: 0 });
  const [offset, setOffset] = useState(0);
  const [newRow, setNewRow] = useState({});
  const [editingPk, setEditingPk] = useState(null);
  const [editValues, setEditValues] = useState({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  // A differenza di `loading` (solo il primo caricamento della pagina),
  // copre ogni cambio di tabella/pagina: senza un indicatore qui, una
  // richiesta lenta o bloccata lascia la pagina muta — indistinguibile per
  // l'utente da un caricamento davvero infinito anche quando in realtà
  // arriverà (o fallirà con un errore) tra qualche secondo.
  const [caricandoTabella, setCaricandoTabella] = useState(false);

  // Import CSV/Excel (vedi services/import_engine.py): due passaggi, mai uno
  // solo — prima un'anteprima (nulla scritto, solo il mapping suggerito e le
  // righe che tornerebbero valide/errate), poi la conferma esplicita. Un file
  // con dati storici non va scritto alla cieca al primo caricamento.
  const [mostraImport, setMostraImport] = useState(false);
  const [importFile, setImportFile] = useState(null);
  const [importAnalisi, setImportAnalisi] = useState(null); // risposta del backend, esegui=false
  const [importMapping, setImportMapping] = useState({}); // colonna tabella -> intestazione file, modificabile
  const [importando, setImportando] = useState(false);
  const [importRisultato, setImportRisultato] = useState(null); // risposta del backend, esegui=true
  const [erroreImport, setErroreImport] = useState("");

  useEffect(() => {
    api
      .get("/integrations")
      .then((res) => {
        const dbIntegrations = res.data.filter(
          (i) => i.kind === "database_external" || i.kind === "database_managed"
        );
        setIntegrations(dbIntegrations);
        if (dbIntegrations.length > 0) setIntegrationId(dbIntegrations[0].id);
      })
      .catch(() => setError("Impossibile caricare le integrazioni."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!integrationId) {
      setTables([]);
      setTableName(null);
      return;
    }
    setError("");
    api
      .get(`/integrations/${integrationId}/tables`)
      .then((res) => {
        setTables(res.data.tables);
        setTableName(res.data.tables[0] ?? null);
      })
      .catch(() => setError("Impossibile leggere le tabelle di questo database."));
  }, [integrationId]);

  useEffect(() => {
    // tableName può essere ancora quello dell'integrazione precedente per un
    // istante, finché l'effetto sopra non ha finito di aggiornarlo: senza
    // questo controllo si parte con una fetch su una tabella che non esiste
    // più per la nuova integrazione (404 di transizione, visibile come errore
    // lampeggiante nella UI).
    if (!integrationId || !tableName || !tables.includes(tableName)) {
      setSchema([]);
      setRowsData({ columns: [], primary_key: null, rows: [], total: 0 });
      return;
    }
    setOffset(0);
    loadSchemaAndRows(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [integrationId, tableName]);

  async function loadSchemaAndRows(newOffset) {
    setError("");
    setCaricandoTabella(true);
    try {
      const [schemaRes, rowsRes] = await Promise.all([
        api.get(`/integrations/${integrationId}/tables/${tableName}/schema`),
        api.get(`/integrations/${integrationId}/tables/${tableName}/rows`, {
          params: { limit: PAGE_SIZE, offset: newOffset },
        }),
      ]);
      setSchema(schemaRes.data.columns);
      setRowsData(rowsRes.data);
      setOffset(newOffset);
      setNewRow({});
      setEditingPk(null);
    } catch (err) {
      setError(
        err.code === "ECONNABORTED"
          ? "Il database collegato non ha risposto in tempo. Riprova: se il problema persiste, la connessione al database potrebbe essere caduta."
          : "Impossibile leggere questa tabella."
      );
    } finally {
      setCaricandoTabella(false);
    }
  }

  const editableColumns = schema.filter((c) => !c.primary_key);

  function apriImport() {
    setMostraImport(true);
    setImportFile(null);
    setImportAnalisi(null);
    setImportMapping({});
    setImportRisultato(null);
    setErroreImport("");
  }

  async function analizzaImport(file, mappingDaUsare) {
    setErroreImport("");
    setImportando(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      if (mappingDaUsare) formData.append("mapping", JSON.stringify(mappingDaUsare));
      const { data } = await api.post(
        `/integrations/${integrationId}/tables/${tableName}/import?esegui=false`,
        formData
      );
      setImportAnalisi(data);
      setImportMapping(data.mapping);
    } catch (err) {
      setErroreImport(err.response?.data?.detail ?? "Impossibile leggere questo file.");
      setImportAnalisi(null);
    } finally {
      setImportando(false);
    }
  }

  function handleImportFileChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportFile(file);
    analizzaImport(file, null); // primo passaggio: mapping suggerito dal backend
  }

  function aggiornaMapping(colonna, intestazioneFile) {
    const nuovoMapping = { ...importMapping, [colonna]: intestazioneFile };
    if (!intestazioneFile) delete nuovoMapping[colonna];
    setImportMapping(nuovoMapping);
    // Rianalizza subito con il mapping corretto: l'anteprima e gli errori
    // mostrati devono sempre riflettere il mapping che si sta per confermare,
    // non quello suggerito all'inizio.
    if (importFile) analizzaImport(importFile, nuovoMapping);
  }

  async function confermaImport() {
    if (!importFile) return;
    setErroreImport("");
    setImportando(true);
    try {
      const formData = new FormData();
      formData.append("file", importFile);
      formData.append("mapping", JSON.stringify(importMapping));
      const { data } = await api.post(
        `/integrations/${integrationId}/tables/${tableName}/import?esegui=true`,
        formData
      );
      setImportRisultato(data);
      await loadSchemaAndRows(0); // la tabella ha righe nuove: si riparte dalla prima pagina
    } catch (err) {
      setErroreImport(err.response?.data?.detail ?? "Impossibile completare l'import.");
    } finally {
      setImportando(false);
    }
  }

  async function handleAddRow(e) {
    e.preventDefault();
    setError("");
    try {
      await api.post(`/integrations/${integrationId}/tables/${tableName}/rows`, { values: newRow });
      await loadSchemaAndRows(offset);
    } catch {
      setError("Impossibile aggiungere la riga. Controlla i campi obbligatori.");
    }
  }

  function startEdit(row) {
    setEditingPk(row[rowsData.primary_key]);
    const values = {};
    for (const col of editableColumns) values[col.name] = row[col.name] ?? "";
    setEditValues(values);
  }

  async function handleSaveEdit(pkValue) {
    setError("");
    try {
      await api.put(`/integrations/${integrationId}/tables/${tableName}/rows/${pkValue}`, { values: editValues });
      await loadSchemaAndRows(offset);
    } catch {
      setError("Impossibile salvare le modifiche.");
    }
  }

  async function handleDeleteRow(pkValue) {
    setError("");
    try {
      await api.delete(`/integrations/${integrationId}/tables/${tableName}/rows/${pkValue}`);
      await loadSchemaAndRows(offset);
    } catch {
      setError("Impossibile eliminare la riga.");
    }
  }

  return (
    <div className="flex">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Topbar />
        <main className="p-6 flex-1 space-y-6">
          <div className="flex items-center gap-2">
            <Database size={20} className="text-slate-400" aria-hidden="true" />
            <h1 className="text-lg font-semibold text-slate-800">Dati</h1>
          </div>

          {loading && <p className="text-sm text-slate-500">Caricamento...</p>}

          {!loading && integrations.length === 0 && (
            <p className="text-sm text-slate-500">
              Nessun database collegato ancora. Vai su Integrazioni per collegarne uno esterno o
              per farne provisionare uno da Cortex.
            </p>
          )}

          {integrations.length > 0 && (
            <div className="flex gap-3 flex-wrap">
              <select
                value={integrationId ?? ""}
                onChange={(e) => setIntegrationId(Number(e.target.value))}
                className="border border-slate-300 rounded-md px-3 py-2 text-sm bg-white"
              >
                {integrations.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name}
                  </option>
                ))}
              </select>

              {tables.length > 0 && (
                <select
                  value={tableName ?? ""}
                  onChange={(e) => setTableName(e.target.value)}
                  className="border border-slate-300 rounded-md px-3 py-2 text-sm bg-white"
                >
                  {tables.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              )}

              {tableName && (
                <>
                  <button
                    onClick={() =>
                      scaricaFile(`/integrations/${integrationId}/tables/${tableName}/export.xlsx`, `${tableName}.xlsx`)
                    }
                    className="flex items-center gap-1 text-sm font-medium text-slate-600 hover:text-slate-900 px-3 py-2"
                  >
                    <Download size={14} /> Esporta Excel
                  </button>
                  <button
                    onClick={apriImport}
                    className="flex items-center gap-1 text-sm font-medium text-slate-600 hover:text-slate-900 px-3 py-2"
                  >
                    <Upload size={14} /> Importa CSV/Excel
                  </button>
                </>
              )}
            </div>
          )}

          {mostraImport && tableName && (
            <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-700">
                  Importa in "{tableName}"
                </h2>
                <button
                  onClick={() => setMostraImport(false)}
                  aria-label="Chiudi import"
                  className="text-slate-400 hover:text-slate-700"
                >
                  <X size={16} />
                </button>
              </div>

              <div>
                <input type="file" accept=".csv,.xlsx,.xlsm" onChange={handleImportFileChange} className="text-sm" />
                <p className="text-xs text-slate-400 mt-1">CSV o Excel. Nulla viene scritto finché non confermi.</p>
              </div>

              {erroreImport && <p className="text-sm text-red-600">{erroreImport}</p>}
              {importando && <p className="text-sm text-slate-400">Analisi in corso...</p>}

              {importAnalisi && !importRisultato && (
                <div className="space-y-4">
                  <div>
                    <h3 className="text-xs font-semibold text-slate-500 mb-2">
                      Colonna dove va — corretto se serve
                    </h3>
                    <div className="grid grid-cols-2 gap-3">
                      {importAnalisi.colonne_tabella.map((colonna) => (
                        <div key={colonna} className="flex items-center gap-2">
                          <span className="text-xs text-slate-500 w-32 shrink-0 truncate" title={colonna}>
                            {colonna}
                          </span>
                          <select
                            value={importMapping[colonna] ?? ""}
                            onChange={(e) => aggiornaMapping(colonna, e.target.value)}
                            className="flex-1 border border-slate-300 rounded-md px-2 py-1 text-xs"
                          >
                            <option value="">— non importare —</option>
                            {importAnalisi.colonne_file.map((intestazione) => (
                              <option key={intestazione} value={intestazione}>
                                {intestazione}
                              </option>
                            ))}
                          </select>
                        </div>
                      ))}
                    </div>
                  </div>

                  <p className="text-sm text-slate-600">
                    {importAnalisi.totale} righe nel file — {importAnalisi.valide} valide
                    {importAnalisi.errori.length > 0 && `, ${importAnalisi.errori.length} con errori`}.
                  </p>

                  {importAnalisi.errori.length > 0 && (
                    <ul className="text-xs text-red-600 space-y-0.5 max-h-32 overflow-y-auto">
                      {importAnalisi.errori.slice(0, 20).map((e, i) => (
                        <li key={i}>
                          Riga {e.riga}: {e.errore}
                        </li>
                      ))}
                      {importAnalisi.errori.length > 20 && (
                        <li>+{importAnalisi.errori.length - 20} altre</li>
                      )}
                    </ul>
                  )}

                  {importAnalisi.anteprima.length > 0 && (
                    <div className="overflow-x-auto border border-slate-100 rounded-md">
                      <table className="w-full text-xs">
                        <thead className="bg-slate-50 text-slate-500">
                          <tr>
                            {Object.keys(importMapping).map((c) => (
                              <th key={c} className="px-2 py-1 text-left font-medium whitespace-nowrap">
                                {c}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {importAnalisi.anteprima.slice(0, 5).map((riga, i) => (
                            <tr key={i} className="border-t border-slate-100">
                              {Object.keys(importMapping).map((c) => (
                                <td key={c} className="px-2 py-1 whitespace-nowrap">
                                  {String(riga[c] ?? "")}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {isAdmin ? (
                    <button
                      onClick={confermaImport}
                      disabled={importando || importAnalisi.valide === 0}
                      className="px-4 py-2 rounded-md bg-slate-800 text-white text-sm font-medium disabled:opacity-50"
                    >
                      {importando ? "Importazione..." : `Conferma import (${importAnalisi.valide} righe)`}
                    </button>
                  ) : (
                    <p className="text-xs text-slate-500">
                      Sei in sola lettura: puoi vedere l'anteprima ma non completare l'import.
                    </p>
                  )}
                </div>
              )}

              {importRisultato && (
                <p className="text-sm text-emerald-700">
                  {importRisultato.inserite} righe importate
                  {importRisultato.errori.length > 0 && ` — ${importRisultato.errori.length} scartate (vedi sopra)`}.
                </p>
              )}
            </div>
          )}

          {!isAdmin && tableName && (
            <p className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-lg p-4">
              Sei in sola lettura: puoi consultare ed esportare questa tabella ma non aggiungere, modificare o
              eliminare righe, né completare un import.
            </p>
          )}

          {error && <p className="text-sm text-red-600">{error}</p>}

          {caricandoTabella && <p className="text-sm text-slate-500">Caricamento tabella...</p>}

          {integrationId && tables.length === 0 && !error && (
            <p className="text-sm text-slate-500">Questo database non ha ancora nessuna tabella.</p>
          )}

          {tableName && (
            <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-slate-500 text-left">
                    <tr>
                      {rowsData.columns.map((col) => (
                        <th key={col} className="px-4 py-2 font-medium whitespace-nowrap">
                          {col}
                        </th>
                      ))}
                      <th className="px-4 py-2 w-24"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {rowsData.rows.map((row) => {
                      const pkValue = row[rowsData.primary_key];
                      const isEditing = editingPk === pkValue;
                      return (
                        <tr key={pkValue} className="border-t border-slate-100">
                          {rowsData.columns.map((col) => (
                            <td key={col} className="px-4 py-2 whitespace-nowrap">
                              {isEditing && col !== rowsData.primary_key ? (
                                <input
                                  type={inputTypeFor(schema.find((c) => c.name === col)?.type ?? "")}
                                  value={editValues[col] ?? ""}
                                  onChange={(e) =>
                                    setEditValues((prev) => ({ ...prev, [col]: e.target.value }))
                                  }
                                  className="border border-slate-300 rounded px-2 py-1 text-sm w-full"
                                />
                              ) : (
                                String(row[col] ?? "")
                              )}
                            </td>
                          ))}
                          <td className="px-4 py-2 whitespace-nowrap">
                            {isEditing ? (
                              <div className="flex gap-1">
                                <button
                                  onClick={() => handleSaveEdit(pkValue)}
                                  className="text-emerald-600 text-xs font-medium px-2 py-1"
                                >
                                  Salva
                                </button>
                                <button
                                  onClick={() => setEditingPk(null)}
                                  aria-label="Annulla modifica"
                                  className="text-slate-400 p-1"
                                >
                                  <X size={14} />
                                </button>
                              </div>
                            ) : (
                              isAdmin && (
                                <div className="flex gap-1">
                                  <button
                                    onClick={() => startEdit(row)}
                                    aria-label="Modifica riga"
                                    className="text-slate-400 hover:text-slate-700 p-1"
                                  >
                                    <Pencil size={14} />
                                  </button>
                                  <button
                                    onClick={() => handleDeleteRow(pkValue)}
                                    aria-label="Elimina riga"
                                    className="text-slate-400 hover:text-red-600 p-1"
                                  >
                                    <Trash2 size={14} />
                                  </button>
                                </div>
                              )
                            )}
                          </td>
                        </tr>
                      );
                    })}

                    {isAdmin && (
                      <tr className="border-t border-slate-200 bg-slate-50/50">
                        {editableColumns.map((col) => (
                          <td key={col.name} className="px-4 py-2">
                            <input
                              type={inputTypeFor(col.type)}
                              placeholder={col.name}
                              value={newRow[col.name] ?? ""}
                              onChange={(e) => setNewRow((prev) => ({ ...prev, [col.name]: e.target.value }))}
                              className="border border-slate-300 rounded px-2 py-1 text-sm w-full"
                            />
                          </td>
                        ))}
                        {rowsData.primary_key && <td className="px-4 py-2 text-xs text-slate-400">auto</td>}
                        <td className="px-4 py-2">
                          <button
                            onClick={handleAddRow}
                            aria-label="Aggiungi riga"
                            className="text-slate-700 hover:text-slate-900 p-1"
                          >
                            <Plus size={16} />
                          </button>
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div className="flex items-center justify-between px-4 py-3 border-t border-slate-200 text-xs text-slate-500">
                <span>
                  {rowsData.total} righe totali — {offset + 1}–{Math.min(offset + PAGE_SIZE, rowsData.total)}
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={() => loadSchemaAndRows(Math.max(offset - PAGE_SIZE, 0))}
                    disabled={offset === 0}
                    className="p-1 disabled:opacity-30"
                    aria-label="Pagina precedente"
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <button
                    onClick={() => loadSchemaAndRows(offset + PAGE_SIZE)}
                    disabled={offset + PAGE_SIZE >= rowsData.total}
                    className="p-1 disabled:opacity-30"
                    aria-label="Pagina successiva"
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
