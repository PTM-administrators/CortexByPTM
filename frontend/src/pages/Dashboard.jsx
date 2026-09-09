// Dashboard che si adatta in base al settore (industry) dell'utente.
// La configurazione (widget, statistiche, etichetta settore) arriva già pronta
// da AuthContext, che la carica da /api/dashboard una volta al login: evita di
// rifare la stessa chiamata che serve anche alla Sidebar.
//
// "Vista generata": quello che l'agente costruisce in risposta a una domanda
// sui dati (grafico, tabella, schede) appare qui nella pagina principale, non
// dentro la finestra della chat — la chat resta solo il comando che la aggiorna
// (vedi AgentChat.jsx, che riceve `onWidget` per scriverci dentro). Se la vista
// arriva da una Vista salvata richiamata per nome (vedi agent_brain.py
// ._try_saved_view) e ha azioni per riga, il bottone funziona anche qui — stesso
// flusso di conferma di Viste.jsx, solo innescato dalla chat invece che dal form.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BellRing, Plug, ArrowRight } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import Sidebar from "../components/layout/Sidebar";
import Topbar from "../components/layout/Topbar";
import Card from "../components/ui/Card";
import AgentChat from "../components/chat/AgentChat";
import WidgetCanvas from "../components/widgets/WidgetCanvas";
import api from "../services/api";

const MAX_SEGNALAZIONI_DASHBOARD = 3; // il resto si vede su /segnalazioni, qui solo un assaggio

function fmtEuro(value) {
  return new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(value ?? 0);
}

// Un'azienda appena registrata non ha ancora nessuna integrazione: prima
// del 25 agosto 2026 vedeva comunque le card segnaposto "Overview 0" /
// "Recent Activity 0" — sembrava rotta, e senza nessuna indicazione su
// cosa fare per primo. Al loro posto, un invito chiaro a collegare
// qualcosa — il primo vero passo, non un numero finto.
function InvitoIniziale() {
  return (
    <div className="bg-white border border-dashed border-slate-300 rounded-lg p-8 text-center space-y-3">
      <Plug size={28} className="mx-auto text-slate-300" aria-hidden="true" />
      <h2 className="text-sm font-semibold text-slate-700">Inizia collegando la tua azienda</h2>
      <p className="text-sm text-slate-500 max-w-md mx-auto">
        Cortex non ha ancora nulla da mostrare perché non hai collegato nessun dato. Hai già un
        gestionale (es. un programma di contabilità)? Collegalo. Non hai nulla? Cortex può crearti
        un database pronto in un click.
      </p>
      <Link
        to="/integrations"
        className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md bg-slate-800 text-white text-sm font-medium"
      >
        Vai a Integrazioni <ArrowRight size={14} aria-hidden="true" />
      </Link>
    </div>
  );
}

// Riepilogo reale (liquidità + perché è cambiata) al posto delle statistiche
// segnaposto: mostrato solo se l'azienda ha un database contabile collegato
// riconosciuto (vedi api/dashboard.py._riepilogo_finanziario) — altrimenti
// il chiamante ricade sulle card generiche per settore, invariate.
function RiepilogoFinanziario({ riepilogo }) {
  const conti = Object.entries(riepilogo.saldi);
  return (
    <div className="space-y-4">
      {riepilogo.avviso_cassa && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <BellRing size={16} className="text-red-600 mt-0.5 shrink-0" aria-hidden="true" />
          <div>
            <p className="text-sm font-medium text-red-700">{riepilogo.avviso_cassa}</p>
            <Link to="/contabilita" className="text-xs font-medium text-red-600 hover:text-red-800">
              Vedi la previsione di cassa →
            </Link>
          </div>
        </div>
      )}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {conti.slice(0, 3).map(([conto, valore]) => (
          <Card key={conto} title={conto} value={fmtEuro(valore)} />
        ))}
        <Card title="Liquidità totale" value={fmtEuro(riepilogo.totale_liquidita)} />
      </div>
      {riepilogo.totale_liquidita === 0 && conti.length > 0 && (
        <p className="text-xs text-slate-400">
          Nessun movimento risulta mai registrato sui conti di liquidità in questo database collegato.
        </p>
      )}
      {riepilogo.narrazione && (
        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-slate-600 mb-2">
            Cosa è cambiato{riepilogo.periodo ? ` — ${riepilogo.periodo}` : ""}
          </h2>
          <p className="text-sm text-slate-600 leading-relaxed">{riepilogo.narrazione}</p>
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const { industryConfig } = useAuth();
  const [vista, setVista] = useState(null);

  const [pendingRowAction, setPendingRowAction] = useState(null); // {id, preview}
  const [confirming, setConfirming] = useState(false);
  const [rowActionNotice, setRowActionNotice] = useState("");

  // Segnalazioni proattive (vedi Segnalazioni.jsx, api/alerts.py): calcolate
  // al caricamento della pagina, non richieste dall'utente — è il punto
  // dell'agente che "nota da solo" invece di aspettare una domanda in chat.
  const [segnalazioni, setSegnalazioni] = useState([]);
  useEffect(() => {
    api
      .get("/alerts/segnalazioni")
      .then((res) => setSegnalazioni(res.data))
      .catch(() => setSegnalazioni([]));
  }, []);

  async function handleRowAction(pkValue, actionIndex) {
    if (!vista?.view_id) return;
    setRowActionNotice("");
    try {
      const { data } = await api.post(`/views/${vista.view_id}/rows/${pkValue}/actions/${actionIndex}`);
      setPendingRowAction({ id: data.id, preview: data.preview });
    } catch (err) {
      setRowActionNotice(err.response?.data?.detail ?? "Impossibile preparare l'azione.");
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

  return (
    <div className="flex">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Topbar />
        <main className="p-6 flex-1 grid grid-cols-1 lg:grid-cols-3 gap-6">
          <section className="lg:col-span-2 space-y-6">
            <h1 className="text-lg font-semibold text-slate-800">
              {industryConfig.industry_label
                ? `Dashboard — ${industryConfig.industry_label}`
                : "Dashboard"}
            </h1>

            {industryConfig.riepilogo_finanziario ? (
              <RiepilogoFinanziario riepilogo={industryConfig.riepilogo_finanziario} />
            ) : industryConfig.numero_integrazioni === 0 ? (
              <InvitoIniziale />
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                {(industryConfig.widgets ?? []).map((w) => (
                  <Card key={w} title={w} value={industryConfig.stats?.[w] ?? 0} />
                ))}
              </div>
            )}

            {segnalazioni.length > 0 && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-semibold text-amber-800">
                    <BellRing size={16} aria-hidden="true" />
                    Segnalazioni ({segnalazioni.length})
                  </div>
                  <Link to="/segnalazioni" className="text-xs font-medium text-amber-700 hover:text-amber-900">
                    Vedi tutte →
                  </Link>
                </div>
                <ul className="space-y-1">
                  {segnalazioni.slice(0, MAX_SEGNALAZIONI_DASHBOARD).map((s, i) => (
                    <li key={`${s.regola_id}-${s.pk}-${i}`} className="text-sm text-slate-700">
                      {s.messaggio}
                    </li>
                  ))}
                </ul>
                {segnalazioni.length > MAX_SEGNALAZIONI_DASHBOARD && (
                  <p className="text-xs text-amber-700">
                    +{segnalazioni.length - MAX_SEGNALAZIONI_DASHBOARD} altre
                  </p>
                )}
              </div>
            )}

            <div>
              <h2 className="text-sm font-semibold text-slate-600 mb-3">Vista generata</h2>
              <WidgetCanvas spec={vista} onRowAction={handleRowAction} />
            </div>

            {pendingRowAction && (
              <div className="bg-white border border-amber-300 rounded-lg p-4 space-y-2">
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
              </div>
            )}
            {rowActionNotice && <p className="text-sm text-emerald-700">{rowActionNotice}</p>}
          </section>

          <section className="h-[70vh]">
            <AgentChat onWidget={setVista} />
          </section>
        </main>
      </div>
    </div>
  );
}
