// Dispatcher per tutto ciò che l'agente può mostrare nella pagina principale
// (vedi Dashboard.jsx, backend/app/services/agent_brain.py._handle_visualize):
// barre singole/raggruppate/impilate, linea, tabella, schede — la forma la
// sceglie il backend in base al tipo di richiesta, non l'utente.
//
// Palette e regole dalla skill "dataviz": ordine categorico fisso (mai colori
// ciclati a caso), tratti sottili, tooltip sempre presente, legenda solo da 2
// serie in su (una singola serie è già nominata dal titolo), separatore chiaro
// tra segmenti impilati.
import { useState } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import Card from "../ui/Card";
import api from "../../services/api";

// Palette categorica validata (color-blind safe, ordine fisso, mai ciclata).
const SERIE_COLORI = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];
const INK_SECONDARY = "#52514e";
const MUTED = "#898781";
const GRIDLINE = "#e1e0d9";
const SURFACE = "#ffffff";

const fmtEuro = (value) =>
  new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(value ?? 0);

function Widget({ title, children }) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4">
      <div className="text-sm font-medium text-slate-700 mb-3">{title}</div>
      {children}
    </div>
  );
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-slate-200 rounded-md shadow-sm px-3 py-2 text-xs space-y-1">
      <div className="font-medium text-slate-700">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: p.color }} />
          <span className="text-slate-500">{p.name}:</span>
          <span className="font-mono text-slate-800">{fmtEuro(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

function toRows(labels, series) {
  return labels.map((label, i) => {
    const row = { label };
    series.forEach((s) => {
      row[s.name] = s.data[i];
    });
    return row;
  });
}

function BarWidget({ spec, stacked }) {
  const { title, labels, series } = spec;
  const data = toRows(labels, series);
  const altezza = Math.max(140, labels.length * (stacked ? 70 : 32));
  const mostraLegenda = stacked || series.length > 1;

  return (
    <Widget title={title}>
      <ResponsiveContainer width="100%" height={altezza}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid horizontal={false} stroke={GRIDLINE} />
          <XAxis type="number" tick={{ fill: MUTED, fontSize: 11 }} axisLine={{ stroke: GRIDLINE }} tickLine={false} />
          <YAxis
            dataKey="label"
            type="category"
            tick={{ fill: INK_SECONDARY, fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            width={160}
          />
          <Tooltip content={<ChartTooltip />} />
          {mostraLegenda && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {series.map((s, i) => (
            <Bar
              key={s.name}
              dataKey={s.name}
              stackId={stacked ? "a" : undefined}
              fill={SERIE_COLORI[i % SERIE_COLORI.length]}
              stroke={stacked ? SURFACE : undefined}
              strokeWidth={stacked ? 2 : 0}
              radius={stacked ? 0 : [0, 4, 4, 0]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </Widget>
  );
}

function LineWidget({ spec }) {
  const { title, labels, series } = spec;
  const data = toRows(labels, series);

  return (
    <Widget title={title}>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ top: 4, right: 12, left: 0, bottom: 4 }}>
          <CartesianGrid vertical={false} stroke={GRIDLINE} />
          <XAxis dataKey="label" tick={{ fill: MUTED, fontSize: 11 }} axisLine={{ stroke: GRIDLINE }} tickLine={false} />
          <YAxis tick={{ fill: MUTED, fontSize: 11 }} axisLine={false} tickLine={false} width={56} />
          <Tooltip content={<ChartTooltip />} />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {series.map((s, i) => (
            <Line
              key={s.name}
              type="monotone"
              dataKey={s.name}
              stroke={SERIE_COLORI[i % SERIE_COLORI.length]}
              strokeWidth={2}
              dot={{ r: 4, fill: SERIE_COLORI[i % SERIE_COLORI.length] }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </Widget>
  );
}

function TableWidget({ spec, onRowAction }) {
  const { title, columns, rows, primary_key: primaryKey, actions } = spec;
  const hasActions = onRowAction && actions?.length > 0;

  return (
    <Widget title={title}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200">
              {columns.map((c) => (
                <th key={c.key} className="text-left font-medium text-slate-500 px-3 py-2 whitespace-nowrap">
                  {c.label}
                </th>
              ))}
              {hasActions && <th className="px-3 py-2" />}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={row[primaryKey] ?? i} className="border-b border-slate-100">
                {columns.map((c) => (
                  <td key={c.key} className="px-3 py-2 text-slate-700 whitespace-nowrap">
                    {c.key === "importo" ? fmtEuro(row[c.key]) : String(row[c.key] ?? "")}
                  </td>
                ))}
                {hasActions && (
                  <td className="px-3 py-2 whitespace-nowrap">
                    <div className="flex gap-2">
                      {actions.map((a, actionIndex) => (
                        <button
                          key={a.name}
                          onClick={() => onRowAction(row[primaryKey], actionIndex, a.name)}
                          className="text-xs px-2 py-1 rounded-md bg-slate-800 text-white font-medium"
                        >
                          {a.name}
                        </button>
                      ))}
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && <p className="text-xs text-slate-400 py-3">Nessuna riga trovata.</p>}
    </Widget>
  );
}

// "Prezzo_al_mq" -> "Prezzo al mq": solo per rendere leggibile il nome del
// campo così com'è nella sorgente (colonna SQL o chiave JSON), senza un
// dizionario di traduzioni per settore — resta generico.
function formattaChiave(chiave) {
  const testo = chiave.replace(/_/g, " ").trim();
  return testo.charAt(0).toUpperCase() + testo.slice(1);
}

function formattaValore(valore) {
  if (valore === null || valore === undefined || valore === "") return "—";
  if (typeof valore === "boolean") return valore ? "Sì" : "No";
  if (typeof valore === "object") return JSON.stringify(valore);
  return String(valore);
}

// Il dettaglio completo di una scheda (GET /views/{view_id}/rows/{pk}):
// per una vista su database sono le stesse colonne già viste, per una vista
// su API REST possono essere molti più campi di quelli usati per
// titolo/sottotitolo/badge (vedi app.services.api_connector sul backend).
function DettaglioSchedaModal({ titolo, dati, caricando, errore, onClose }) {
  return (
    <div
      className="fixed inset-0 bg-slate-900/40 flex items-center justify-center p-4 z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl max-w-lg w-full max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 border-b border-slate-200 sticky top-0 bg-white">
          <h3 className="text-sm font-semibold text-slate-800">{titolo}</h3>
          <button onClick={onClose} aria-label="Chiudi" className="text-slate-400 hover:text-slate-700 p-1">
            <X size={16} />
          </button>
        </div>
        <div className="p-4">
          {caricando && <p className="text-sm text-slate-400">Caricamento dettagli...</p>}
          {errore && <p className="text-sm text-red-600">{errore}</p>}
          {!caricando && !errore && dati && (
            <dl className="space-y-2 text-sm">
              {Object.entries(dati).map(([chiave, valore]) => (
                <div key={chiave} className="flex flex-col gap-0.5 border-b border-slate-100 pb-2 last:border-0">
                  <dt className="text-xs text-slate-400">{formattaChiave(chiave)}</dt>
                  <dd className="text-slate-700 break-words">{formattaValore(valore)}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>
    </div>
  );
}

function EntityCardsWidget({ spec }) {
  const { title, items, view_id: viewId } = spec;
  const [espansa, setEspansa] = useState(null); // { titolo, dati, caricando, errore }

  function espandi(item) {
    if (!viewId || item._pk === undefined || item._pk === null) return;
    setEspansa({ titolo: item.titolo || title, dati: null, caricando: true, errore: "" });
    api
      .get(`/views/${viewId}/rows/${item._pk}`)
      .then((res) => setEspansa({ titolo: item.titolo || title, dati: res.data, caricando: false, errore: "" }))
      .catch((err) =>
        setEspansa({
          titolo: item.titolo || title,
          dati: null,
          caricando: false,
          errore: err.response?.data?.detail ?? "Impossibile caricare i dettagli.",
        })
      );
  }

  const espandibile = Boolean(viewId);

  return (
    <Widget title={title}>
      {items.length === 0 ? (
        <p className="text-xs text-slate-400">Nessuna riga trovata.</p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {items.map((item, i) => (
            <div
              key={item._pk ?? i}
              onClick={espandibile ? () => espandi(item) : undefined}
              className={`border border-slate-200 rounded-lg p-4 ${
                espandibile ? "cursor-pointer hover:border-slate-400 hover:shadow-sm transition" : ""
              }`}
            >
              <div className="font-medium text-slate-800">{item.titolo}</div>
              {item.sottotitolo && <div className="text-sm text-slate-500 mt-1">{item.sottotitolo}</div>}
              {item.badge && (
                <span className="inline-block mt-2 text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
                  {item.badge}
                </span>
              )}
              {espandibile && <div className="text-[10px] text-slate-400 mt-2">Clicca per i dettagli</div>}
            </div>
          ))}
        </div>
      )}
      {espansa && (
        <DettaglioSchedaModal
          titolo={espansa.titolo}
          dati={espansa.dati}
          caricando={espansa.caricando}
          errore={espansa.errore}
          onClose={() => setEspansa(null)}
        />
      )}
    </Widget>
  );
}

const GIORNI_SETTIMANA = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];
const MESI_IT = [
  "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
  "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
];

function CalendarWidget({ spec }) {
  const { title, events } = spec;
  const primoEvento = events[0]?.data;
  const [cursore, setCursore] = useState(() => {
    const base = primoEvento ? new Date(primoEvento) : new Date();
    return new Date(base.getFullYear(), base.getMonth(), 1);
  });

  const eventiPerGiorno = {};
  for (const ev of events) {
    (eventiPerGiorno[ev.data] ??= []).push(ev);
  }

  const anno = cursore.getFullYear();
  const mese = cursore.getMonth();
  const primoGiornoMese = new Date(anno, mese, 1);
  const giorniNelMese = new Date(anno, mese + 1, 0).getDate();
  // Lunedì = 0: getDay() ha Domenica = 0, la ruotiamo.
  const offset = (primoGiornoMese.getDay() + 6) % 7;

  const celle = [];
  for (let i = 0; i < offset; i++) celle.push(null);
  for (let giorno = 1; giorno <= giorniNelMese; giorno++) celle.push(giorno);

  const isoData = (giorno) => `${anno}-${String(mese + 1).padStart(2, "0")}-${String(giorno).padStart(2, "0")}`;

  return (
    <Widget title={title}>
      <div className="flex items-center justify-between mb-3">
        <button
          onClick={() => setCursore(new Date(anno, mese - 1, 1))}
          aria-label="Mese precedente"
          className="p-1 rounded-md hover:bg-slate-100"
        >
          <ChevronLeft size={16} />
        </button>
        <div className="text-sm font-medium text-slate-700">
          {MESI_IT[mese]} {anno}
        </div>
        <button
          onClick={() => setCursore(new Date(anno, mese + 1, 1))}
          aria-label="Mese successivo"
          className="p-1 rounded-md hover:bg-slate-100"
        >
          <ChevronRight size={16} />
        </button>
      </div>

      <div className="grid grid-cols-7 gap-1 text-xs">
        {GIORNI_SETTIMANA.map((g) => (
          <div key={g} className="text-center text-slate-400 font-medium pb-1">
            {g}
          </div>
        ))}
        {celle.map((giorno, i) => {
          const eventiGiorno = giorno ? eventiPerGiorno[isoData(giorno)] ?? [] : [];
          return (
            <div
              key={i}
              className={`min-h-[64px] rounded-md border p-1 ${
                giorno ? "border-slate-100" : "border-transparent"
              }`}
            >
              {giorno && (
                <>
                  <div className="text-slate-400">{giorno}</div>
                  <div className="space-y-0.5 mt-0.5">
                    {eventiGiorno.slice(0, 3).map((ev, j) => (
                      <div
                        key={j}
                        className="text-[10px] leading-tight px-1 py-0.5 rounded bg-blue-50 text-blue-700 truncate"
                        title={ev.titolo}
                      >
                        {ev.titolo}
                      </div>
                    ))}
                    {eventiGiorno.length > 3 && (
                      <div className="text-[10px] text-slate-400">+{eventiGiorno.length - 3} altri</div>
                    )}
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </Widget>
  );
}

function NarrativeWidget({ spec }) {
  return (
    <Widget title={spec.title}>
      <p className="text-sm text-slate-600 leading-relaxed">{spec.text}</p>
    </Widget>
  );
}

// Non un grafico singolo ma una composizione di più cose insieme (liquidità,
// cosa è cambiato, previsione, segnalazioni) — la risposta a una domanda
// aperta ("come sta andando l'azienda?") che nessuno dei modi puntuali
// riesce a rendere da solo (vedi agent_brain.py._widget_quadro_generale).
function QuadroGeneraleWidget({ spec }) {
  const conti = Object.entries(spec.liquidita?.saldi ?? {});
  const proiezione = spec.previsione?.proiezione ?? [];
  return (
    <Widget title={spec.title}>
      <div className="space-y-4">
        <div>
          <div className="text-xs font-semibold text-slate-500 mb-2">Liquidità attuale</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {conti.slice(0, 3).map(([conto, valore]) => (
              <Card key={conto} title={conto} value={fmtEuro(valore)} />
            ))}
            <Card title="Totale" value={fmtEuro(spec.liquidita?.totale)} />
          </div>
        </div>

        {spec.cosa_e_cambiato && (
          <div>
            <div className="text-xs font-semibold text-slate-500 mb-1">Cosa è cambiato</div>
            <p className="text-sm text-slate-600 leading-relaxed">{spec.cosa_e_cambiato}</p>
          </div>
        )}

        {proiezione.length > 0 && (
          <div>
            <div className="text-xs font-semibold text-slate-500 mb-1">Previsione di cassa</div>
            {spec.previsione.avviso && (
              <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-md px-2 py-1.5 mb-1.5">
                ⚠ {spec.previsione.avviso}
              </p>
            )}
            <p className="text-sm text-slate-600">
              Flusso medio {fmtEuro(spec.previsione.flusso_medio_mensile)}/mese — a{" "}
              {proiezione[proiezione.length - 1].periodo} stimata {fmtEuro(proiezione[proiezione.length - 1].liquidita_stimata)}.
            </p>
          </div>
        )}

        <div>
          <div className="text-xs font-semibold text-slate-500 mb-1">
            Segnalazioni aperte {spec.segnalazioni_aperte > 0 && `(${spec.segnalazioni_aperte})`}
          </div>
          {spec.segnalazioni_aperte === 0 ? (
            <p className="text-sm text-slate-500">Nessuna al momento.</p>
          ) : (
            <ul className="text-sm text-slate-600 space-y-0.5">
              {(spec.segnalazioni_esempi ?? []).map((m, i) => (
                <li key={i}>• {m}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Widget>
  );
}

function CardsWidget({ spec }) {
  const { title, items } = spec;
  return (
    <Widget title={title}>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {items.map((item) => (
          <Card
            key={item.label}
            title={item.label}
            value={item.format === "currency" ? fmtEuro(item.value) : item.value}
          />
        ))}
      </div>
    </Widget>
  );
}

const ESEMPI = [
  "quanto abbiamo in banca?",
  "mostrami le spese di luglio confrontate con maggio",
  "andamento delle entrate nel 2026",
  "composizione delle spese di agosto",
  "dammi l'elenco dei movimenti di agosto",
  "perché sono aumentate le spese questo mese?",
  "come sta andando l'azienda?",
];

export default function WidgetCanvas({ spec, onRowAction, placeholder }) {
  if (!spec) {
    return (
      <div className="bg-white border border-dashed border-slate-300 rounded-lg p-8 text-center">
        <p className="text-sm text-slate-400 mb-3">
          {placeholder ?? "Chiedi qualcosa all'agente per vedere qui una vista generata al volo."}
        </p>
        {!placeholder && (
          <ul className="text-xs text-slate-400 space-y-1">
            {ESEMPI.map((e) => (
              <li key={e} className="italic">"{e}"</li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  switch (spec.type) {
    case "bar":
    case "grouped_bar":
      return <BarWidget spec={spec} stacked={false} />;
    case "stacked_bar":
      return <BarWidget spec={spec} stacked={true} />;
    case "line":
      return <LineWidget spec={spec} />;
    case "table":
      return <TableWidget spec={spec} onRowAction={onRowAction} />;
    case "cards":
      return <CardsWidget spec={spec} />;
    case "entity_cards":
      return <EntityCardsWidget spec={spec} />;
    case "calendar":
      return <CalendarWidget spec={spec} />;
    case "narrative":
      return <NarrativeWidget spec={spec} />;
    case "quadro_generale":
      return <QuadroGeneraleWidget spec={spec} />;
    default:
      return null;
  }
}
