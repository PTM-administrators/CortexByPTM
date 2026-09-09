// Andamenti: Cortex analizza da solo il database collegato — qualunque
// database, non solo quelli con un profilo contabile riconosciuto — e
// mostra i grafici che trova, senza che l'utente debba costruire una Vista
// o una Segnalazione (vedi backend/app/services/analisi_automatica.py).
// Richiesta esplicita dell'utente (26 agosto 2026): "le viste e le
// segnalazioni sono troppo difficili da programmare, Cortex deve essere un
// software che lo fa in automatico".
import { useEffect, useState } from "react";
import { TrendingUp } from "lucide-react";
import Sidebar from "../components/layout/Sidebar";
import Topbar from "../components/layout/Topbar";
import WidgetCanvas from "../components/widgets/WidgetCanvas";
import api from "../services/api";

export default function Andamenti() {
  const [integrations, setIntegrations] = useState([]);
  const [integrationId, setIntegrationId] = useState(null);
  const [grafici, setGrafici] = useState(null);
  const [caricando, setCaricando] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get("/integrations")
      .then((res) => {
        const esplorabili = res.data.filter(
          (i) => i.kind === "database_external" || i.kind === "database_managed"
        );
        setIntegrations(esplorabili);
        if (esplorabili.length > 0) setIntegrationId(esplorabili[0].id);
      })
      .catch(() => setError("Impossibile caricare le integrazioni."));
  }, []);

  useEffect(() => {
    if (!integrationId) return;
    setError("");
    setCaricando(true);
    api
      .get(`/integrations/${integrationId}/analisi-automatica`)
      .then((res) => setGrafici(res.data))
      .catch((err) =>
        setError(
          err.code === "ECONNABORTED"
            ? "L'analisi ha impiegato troppo tempo. Riprova: se il problema persiste, il database potrebbe avere troppe tabelle da scandagliare."
            : "Impossibile analizzare questa integrazione."
        )
      )
      .finally(() => setCaricando(false));
  }, [integrationId]);

  return (
    <div className="flex">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Topbar />
        <main className="p-6 flex-1 space-y-6 max-w-5xl">
          <div className="flex items-center gap-2">
            <TrendingUp size={20} className="text-slate-400" aria-hidden="true" />
            <h1 className="text-lg font-semibold text-slate-800">Andamenti</h1>
          </div>
          <p className="text-sm text-slate-500 -mt-4">
            Cortex analizza da solo il database collegato e mostra qui gli andamenti che trova —
            nessuna Vista o Segnalazione da configurare. La prima analisi su un database con molte
            tabelle può richiedere qualche secondo; quelle successive sono immediate.
          </p>

          {integrations.length > 1 && (
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
          )}

          {integrations.length === 0 && (
            <p className="text-sm text-slate-500">
              Nessun database collegato. Vai su Integrazioni per collegarne uno.
            </p>
          )}

          {error && <p className="text-sm text-red-600">{error}</p>}

          {caricando && <p className="text-sm text-slate-500">Analisi in corso...</p>}

          {!caricando && grafici && grafici.length === 0 && (
            <p className="text-sm text-slate-500">
              Nessuna tabella con un andamento chiaro trovata in questo database (serve almeno una
              colonna data e una colonna di importo, con dati su più mesi).
            </p>
          )}

          {!caricando && grafici && grafici.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {grafici.map((g) => (
                <div key={g.tabella}>
                  <WidgetCanvas spec={g} placeholder="" onRowAction={() => {}} />
                  <p className="text-xs text-slate-400 mt-1">
                    Tabella "{g.tabella}" — {g.righe_totali} righe totali.
                  </p>
                </div>
              ))}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
