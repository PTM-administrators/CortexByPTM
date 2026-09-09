// Motore contabile: saldi, bilancio, IVA, budget, anomalie e ammortamenti sul
// database collegato del tenant. Due profili possibili, smistati in automatico
// dal backend in base allo schema rilevato (vedi api/accounting.py._e_arca):
// il template "nonprofit_accounting" di Sampeyre (tutto calcolato da Cortex),
// oppure uno schema Arca (services/accounting_engine_arca.py — i dati sono
// già nel gestionale, Cortex li legge/ricostruisce dai movimenti veri senza
// inventare nulla). La pagina chiede prima "che profilo è?" e poi mostra la
// vista giusta — non è più specifica di un solo settore.
import { useEffect, useState } from "react";
import { Calculator, AlertTriangle, Upload, CheckCircle2, HelpCircle, Download, ChevronRight, ChevronDown } from "lucide-react";
import Sidebar from "../components/layout/Sidebar";
import Topbar from "../components/layout/Topbar";
import Card from "../components/ui/Card";
import api, { scaricaFile } from "../services/api";

const oggi = new Date();

function fmtEuro(value) {
  return new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(value ?? 0);
}

// Un database aziendale vero ha centinaia di voci di bilancio, molte a
// zero per l'esercizio richiesto (un conto usato solo in certi anni, una
// sotto-voce mai movimentata) — mostrarle tutte è il rumore di cui si è
// lamentato l'utente. Tenuta una voce solo se ha un importo diverso da
// zero, o se — dopo lo stesso filtro applicato ricorsivamente — le resta
// almeno un figlio: un totale a zero con sotto-voci NON a zero (caso raro
// ma possibile, es. costi e ricavi della stessa voce che si annullano) non
// deve sparire silenziosamente.
function nascondiVociAZero(voci) {
  return voci
    .map((v) => ({ ...v, figli: v.figli ? nascondiVociAZero(v.figli) : [] }))
    .filter((v) => v.importo !== 0 || v.figli.length > 0);
}

// Una voce del bilancio Arca (albero: Stato Patrimoniale Attivo/Passivo o
// Conto Economico) — ricorsiva, con indentazione per livello e possibilità
// di aprire/chiudere i rami per non travolgere con centinaia di righe.
function VoceBilancioArca({ voce, profondita = 0 }) {
  const [aperto, setAperto] = useState(profondita < 1);
  const haFigli = voce.figli && voce.figli.length > 0;

  return (
    <div>
      <div
        onClick={() => haFigli && setAperto((a) => !a)}
        className={`flex items-center justify-between px-2 py-1.5 text-sm border-b border-slate-50 ${
          haFigli ? "cursor-pointer hover:bg-slate-50" : ""
        }`}
        style={{ paddingLeft: `${8 + profondita * 16}px` }}
      >
        <span className="flex items-center gap-1 text-slate-700">
          {haFigli ? (
            aperto ? <ChevronDown size={12} className="text-slate-400" /> : <ChevronRight size={12} className="text-slate-400" />
          ) : (
            <span className="w-3" />
          )}
          {voce.descrizione}
        </span>
        <span className={`font-mono ${voce.importo >= 0 ? "text-slate-800" : "text-red-600"}`}>
          {fmtEuro(voce.importo)}
        </span>
      </div>
      {haFigli && aperto && voce.figli.map((f) => <VoceBilancioArca key={f.codice} voce={f} profondita={profondita + 1} />)}
    </div>
  );
}

export default function Contabilita() {
  const [integrations, setIntegrations] = useState([]);
  const [integrationId, setIntegrationId] = useState(null);
  const [profilo, setProfilo] = useState(null); // "sampeyre" | "arca" | null (non ancora determinato)

  const [anno, setAnno] = useState(oggi.getFullYear());
  const [mese, setMese] = useState(oggi.getMonth() + 1);
  const [periodiArca, setPeriodiArca] = useState([]);
  const [periodoArca, setPeriodoArca] = useState("");

  const [saldi, setSaldi] = useState(null);
  const [spiegazione, setSpiegazione] = useState(null); // "cosa è cambiato" — indipendente dall'esercizio scelto, sempre il mese corrente
  const [previsione, setPrevisione] = useState(null); // previsione di cassa — indipendente dall'esercizio scelto, come "cosa è cambiato"
  const [bilancio, setBilancio] = useState(null);
  const [iva, setIva] = useState(null);
  const [ammortamenti, setAmmortamenti] = useState(null);
  const [budget, setBudget] = useState(null);
  const [anomalie, setAnomalie] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  // A differenza di `loading` (solo il primo caricamento della pagina),
  // questo copre ogni ricalcolo dei dati contabili (Passo 3, sotto): senza
  // un indicatore qui, se una di quelle richieste è lenta o si blocca, la
  // pagina resta muta — nessun cambiamento visibile, indistinguibile per
  // l'utente da un vero "caricamento infinito" anche quando in realtà
  // arriverà (o fallirà con un errore) tra qualche secondo.
  const [caricandoDati, setCaricandoDati] = useState(false);
  const [mostraVociAZero, setMostraVociAZero] = useState(false);
  // Sezioni a schede invece di un'unica scrollata: prima del 20 agosto 2026
  // bilancio, IVA, ammortamenti, budget, anomalie e riconciliazione erano
  // tutti impilati e sempre visibili insieme — "troppo incasinato" (feedback
  // dell'utente). Liquidità e "cosa è cambiato" restano invece sempre in
  // vista sopra le schede: sono l'unico riepilogo rapido, non hanno senso
  // nascosti dietro un click.
  const [tabAttiva, setTabAttiva] = useState("bilancio");

  const [fileRiconciliazione, setFileRiconciliazione] = useState(null);
  const [riconciliazione, setRiconciliazione] = useState(null);
  const [riconciliando, setRiconciliando] = useState(false);
  const [erroreRiconciliazione, setErroreRiconciliazione] = useState("");

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

  // Passo 1: che profilo è questa integrazione? Determina quali altre
  // richieste ha senso fare — saldi/budget/anomalie esistono solo per
  // Sampeyre, il bilancio ha una forma diversa a seconda del profilo.
  useEffect(() => {
    if (!integrationId) return;
    setError("");
    setProfilo(null);
    setTabAttiva("bilancio");
    setSaldi(null);
    setSpiegazione(null);
    setPrevisione(null);
    setBilancio(null);
    setIva(null);
    setAmmortamenti(null);
    setBudget(null);
    setAnomalie(null);
    api
      .get(`/integrations/${integrationId}/accounting/profilo`)
      .then((res) => setProfilo(res.data.profilo))
      .catch(() => setError("Impossibile determinare lo schema di questa integrazione."));
  }, [integrationId]);

  // "Cosa è cambiato": spiegazione automatica dello scostamento rispetto al
  // mese precedente (vedi services/narrazione.py) — sempre il mese corrente,
  // indipendente dall'esercizio di bilancio scelto sotto: è un'altra
  // domanda ("come sto andando adesso"), non legata a quale anno si sta
  // consultando nel resto della pagina. Generico per entrambi i profili,
  // stesso endpoint.
  useEffect(() => {
    if (!integrationId || !profilo) return;
    api
      .get(`/integrations/${integrationId}/accounting/spiegazione`)
      .then((res) => setSpiegazione(res.data))
      .catch(() => setSpiegazione(null)); // non bloccante: il resto della pagina resta utile senza
  }, [integrationId, profilo]);

  // Previsione di cassa (vedi services/previsione.py): stessa indipendenza
  // dall'esercizio scelto di "cosa è cambiato" — una proiezione in avanti
  // dalla situazione di oggi, non da un anno di bilancio passato.
  useEffect(() => {
    if (!integrationId || !profilo) return;
    api
      .get(`/integrations/${integrationId}/accounting/previsione-cassa`)
      .then((res) => setPrevisione(res.data))
      .catch(() => setPrevisione(null));
  }, [integrationId, profilo]);

  // Passo 2 (solo profilo Arca): quali esercizi hanno già un bilancio
  // ufficiale — più l'anno in corso, sempre selezionabile anche se Arca non
  // lo ha ancora chiuso: il backend lo calcola al volo dai movimenti reali
  // registrati finora (vedi accounting_engine_arca.compute_bilancio) invece
  // di dare un errore "non trovato".
  useEffect(() => {
    if (!integrationId || profilo !== "arca") return;
    api
      .get(`/integrations/${integrationId}/accounting/periodi-bilancio`)
      .then((res) => {
        const periodi = [...res.data.periodi];
        const annoCorrente = String(oggi.getFullYear());
        if (!periodi.some((p) => p.codice === annoCorrente)) {
          periodi.push({ codice: annoCorrente, descrizione: "In corso (provvisorio)" });
        }
        setPeriodiArca(periodi);
        if (periodi.length > 0) setPeriodoArca(res.data.periodi.length > 0 ? res.data.periodi[res.data.periodi.length - 1].codice : annoCorrente);
      })
      .catch(() => setError("Impossibile leggere gli esercizi di bilancio."));
  }, [integrationId, profilo]);

  // Passo 3 (profilo Arca): saldi + bilancio + IVA + ammortamenti per il
  // periodo scelto. I saldi non dipendono dal periodo (sono "ad oggi", come
  // per Sampeyre) ma li rifacciamo comunque ad ogni cambio per restare
  // coerenti col resto della pagina.
  useEffect(() => {
    if (!integrationId || profilo !== "arca" || !periodoArca) return;
    setError("");
    setCaricandoDati(true);
    const annoNumerico = Number(periodoArca) || oggi.getFullYear();
    Promise.all([
      api.get(`/integrations/${integrationId}/accounting/saldi`),
      api.get(`/integrations/${integrationId}/accounting/bilancio`, { params: { periodo: periodoArca } }),
      api.get(`/integrations/${integrationId}/accounting/iva`, { params: { anno: annoNumerico } }),
      api.get(`/integrations/${integrationId}/accounting/ammortamenti`, { params: { anno: annoNumerico } }),
    ])
      .then(([sRes, bRes, iRes, aRes]) => {
        setSaldi(sRes.data);
        setBilancio(bRes.data);
        setIva(iRes.data);
        setAmmortamenti(aRes.data);
      })
      .catch((err) =>
        setError(
          err.code === "ECONNABORTED"
            ? "Il database collegato non ha risposto in tempo. Riprova: se il problema persiste, la connessione al database potrebbe essere caduta."
            : "Impossibile calcolare i dati contabili per questo periodo."
        )
      )
      .finally(() => setCaricandoDati(false));
  }, [integrationId, profilo, periodoArca]);

  // Passo 3 (profilo Sampeyre): tutto il pacchetto originale, invariato.
  useEffect(() => {
    if (!integrationId || profilo !== "sampeyre") return;
    setError("");
    setCaricandoDati(true);
    Promise.all([
      api.get(`/integrations/${integrationId}/accounting/saldi`),
      api.get(`/integrations/${integrationId}/accounting/bilancio`, { params: { anno } }),
      api.get(`/integrations/${integrationId}/accounting/iva`, { params: { anno } }),
      api.get(`/integrations/${integrationId}/accounting/budget`, { params: { anno, mese } }),
      api.get(`/integrations/${integrationId}/accounting/anomalie`),
    ])
      .then(([saldiRes, bilancioRes, ivaRes, budgetRes, anomalieRes]) => {
        setSaldi(saldiRes.data);
        setBilancio(bilancioRes.data);
        setIva(ivaRes.data);
        setBudget(budgetRes.data);
        setAnomalie(anomalieRes.data.anomalie);
      })
      .catch((err) =>
        setError(
          err.code === "ECONNABORTED"
            ? "Il database collegato non ha risposto in tempo. Riprova: se il problema persiste, la connessione al database potrebbe essere caduta."
            : "Impossibile calcolare i dati contabili. Il database collegato ha lo schema \"Contabilità no-profit\"?"
        )
      )
      .finally(() => setCaricandoDati(false));
  }, [integrationId, profilo, anno, mese]);

  const totaleLiquidita = saldi ? Object.values(saldi).reduce((a, b) => a + b, 0) : 0;

  async function caricaEstrattoConto(e) {
    e.preventDefault();
    if (!fileRiconciliazione || !integrationId) return;

    setRiconciliando(true);
    setErroreRiconciliazione("");
    setRiconciliazione(null);

    const formData = new FormData();
    formData.append("estratto_conto", fileRiconciliazione);

    try {
      const { data } = await api.post(
        `/integrations/${integrationId}/accounting/riconciliazione`,
        formData
      );
      setRiconciliazione(data);
    } catch (err) {
      setErroreRiconciliazione(err.response?.data?.detail ?? "Impossibile leggere il file.");
    } finally {
      setRiconciliando(false);
    }
  }

  // Quali schede esistono dipende dal profilo: Budget/Anomalie/Riconciliazione
  // sono calcolate solo per Sampeyre (vedi Passo 3 sopra, `budget`/`anomalie`
  // restano null per Arca) — nessuna scheda vuota da mostrare per un profilo
  // che quella funzione non ce l'ha.
  const tabs =
    profilo === "arca"
      ? [
          { key: "bilancio", label: "Bilancio" },
          { key: "previsione", label: "Previsione di cassa" },
          { key: "iva", label: "IVA" },
          { key: "ammortamenti", label: "Ammortamenti" },
        ]
      : [
          { key: "bilancio", label: "Bilancio" },
          { key: "previsione", label: "Previsione di cassa" },
          { key: "iva", label: "IVA" },
          { key: "ammortamenti", label: "Ammortamenti" },
          { key: "budget", label: "Budget" },
          { key: "anomalie", label: "Anomalie" },
          { key: "riconciliazione", label: "Riconciliazione bancaria" },
        ];

  return (
    <div className="flex">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Topbar />
        <main className="p-6 flex-1 space-y-6 max-w-5xl">
          <div className="flex items-center gap-2">
            <Calculator size={20} className="text-slate-400" aria-hidden="true" />
            <h1 className="text-lg font-semibold text-slate-800">Contabilità</h1>
          </div>

          {loading && <p className="text-sm text-slate-500">Caricamento...</p>}

          {!loading && integrations.length === 0 && (
            <p className="text-sm text-slate-500">
              Nessun database collegato. Vai su Integrazioni e collega un database (uno schema
              "Contabilità no-profit" o un gestionale Arca) — questa pagina riconosce lo schema da sola.
            </p>
          )}

          {integrations.length > 0 && (
            <div className="flex flex-wrap gap-3 items-center">
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

              {profilo === "arca" ? (
                <label className="text-sm text-slate-500">
                  Esercizio
                  <select
                    value={periodoArca}
                    onChange={(e) => setPeriodoArca(e.target.value)}
                    className="ml-2 border border-slate-300 rounded-md px-2 py-1.5 text-sm bg-white"
                  >
                    {periodiArca.map((p) => (
                      <option key={p.codice} value={p.codice}>
                        {p.descrizione === "In corso (provvisorio)" ? `${p.codice} (provvisorio)` : p.codice}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <>
                  <label className="text-sm text-slate-500">
                    Anno
                    <input
                      type="number"
                      value={anno}
                      onChange={(e) => setAnno(Number(e.target.value))}
                      className="ml-2 w-24 border border-slate-300 rounded-md px-2 py-1.5 text-sm"
                    />
                  </label>
                  <label className="text-sm text-slate-500">
                    Mese (budget)
                    <input
                      type="number"
                      min={1}
                      max={12}
                      value={mese}
                      onChange={(e) => setMese(Number(e.target.value))}
                      className="ml-2 w-16 border border-slate-300 rounded-md px-2 py-1.5 text-sm"
                    />
                  </label>
                </>
              )}
            </div>
          )}

          {error && <p className="text-sm text-red-600">{error}</p>}

          {caricandoDati && (
            <p className="text-sm text-slate-500">Caricamento dati contabili...</p>
          )}

          {saldi && (
            <section>
              <h2 className="text-sm font-semibold text-slate-600 mb-3">Liquidità attuale</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {Object.entries(saldi).map(([conto, valore]) => (
                  <Card key={conto} title={conto} value={fmtEuro(valore)} />
                ))}
                <Card title="Totale" value={fmtEuro(totaleLiquidita)} />
              </div>
            </section>
          )}

          {spiegazione && (
            <section className="bg-white border border-slate-200 rounded-lg p-4">
              <h2 className="text-sm font-semibold text-slate-600 mb-2">
                Cosa è cambiato — {spiegazione.periodo}
              </h2>
              <p className="text-sm text-slate-600 leading-relaxed">{spiegazione.narrazione}</p>
            </section>
          )}

          {profilo && (
            <div className="flex flex-wrap gap-1 border-b border-slate-200">
              {tabs.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setTabAttiva(t.key)}
                  className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px ${
                    tabAttiva === t.key
                      ? "border-slate-800 text-slate-800"
                      : "border-transparent text-slate-500 hover:text-slate-700"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          )}

          {tabAttiva === "bilancio" && bilancio && bilancio.profilo === "arca" && (() => {
            const filtro = mostraVociAZero ? (v) => v : nascondiVociAZero;
            const conto_economico = filtro(bilancio.conto_economico);
            const stato_patrimoniale_attivo = filtro(bilancio.stato_patrimoniale_attivo);
            const stato_patrimoniale_passivo = filtro(bilancio.stato_patrimoniale_passivo);
            return (
            <section>
              <div className="flex items-center gap-2 mb-1">
                <h2 className="text-sm font-semibold text-slate-600">Bilancio {bilancio.periodo}</h2>
                {bilancio.provvisorio && (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">provvisorio</span>
                )}
                <button
                  onClick={() => setMostraVociAZero((m) => !m)}
                  className="ml-auto text-xs font-medium text-slate-500 hover:text-slate-800"
                >
                  {mostraVociAZero ? "Nascondi voci a zero" : "Mostra anche le voci a zero"}
                </button>
              </div>
              {bilancio.provvisorio && (
                <p className="text-xs text-blue-700 bg-blue-50 border border-blue-200 rounded-md px-3 py-2 mb-3">
                  Arca non ha ancora chiuso il bilancio per questo esercizio — ricostruito al volo dai
                  movimenti reali registrati finora, non è un bilancio validato da Arca.
                </p>
              )}
              {bilancio.scarto_da_verificare != null && (
                <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2 mb-3">
                  Il risultato ricalcolato dai movimenti ({fmtEuro(bilancio.risultato_ricalcolato)}) non coincide
                  esattamente con quello ufficiale registrato in Arca ({fmtEuro(bilancio.risultato_esercizio)}) —
                  scarto di {fmtEuro(bilancio.scarto_da_verificare)}, verosimilmente una rettifica non
                  tracciabile dai movimenti contabili.
                </p>
              )}

              <h3 className="text-xs font-semibold text-slate-500 mt-4 mb-2">Conto Economico</h3>
              <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
                {conto_economico.length === 0 ? (
                  <p className="text-xs text-slate-400 px-2 py-3">Nessun movimento in questo esercizio.</p>
                ) : (
                  conto_economico.map((v) => <VoceBilancioArca key={v.codice} voce={v} />)
                )}
              </div>

              <h3 className="text-xs font-semibold text-slate-500 mt-4 mb-2">Stato Patrimoniale — Attivo</h3>
              <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
                {stato_patrimoniale_attivo.length === 0 ? (
                  <p className="text-xs text-slate-400 px-2 py-3">Nessun saldo in questo esercizio.</p>
                ) : (
                  stato_patrimoniale_attivo.map((v) => <VoceBilancioArca key={v.codice} voce={v} />)
                )}
              </div>

              <h3 className="text-xs font-semibold text-slate-500 mt-4 mb-2">Stato Patrimoniale — Passivo</h3>
              <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
                {stato_patrimoniale_passivo.length === 0 ? (
                  <p className="text-xs text-slate-400 px-2 py-3">Nessun saldo in questo esercizio.</p>
                ) : (
                  stato_patrimoniale_passivo.map((v) => <VoceBilancioArca key={v.codice} voce={v} />)
                )}
              </div>

              <p className="text-xs text-slate-400 mt-3">{bilancio.nota}</p>
            </section>
            );
          })()}

          {tabAttiva === "bilancio" && bilancio && bilancio.profilo !== "arca" && (
            <section>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-slate-600">Conto Economico {bilancio.anno}</h2>
                <button
                  onClick={() =>
                    scaricaFile(
                      `/integrations/${integrationId}/accounting/bilancio/export.pdf?anno=${bilancio.anno}`,
                      `Bilancio ${bilancio.anno}.pdf`
                    )
                  }
                  className="flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800"
                >
                  <Download size={12} /> Esporta PDF
                </button>
              </div>
              <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <tbody>
                    {Object.entries(bilancio.conto_economico.per_gruppo).map(([gruppo, valore]) => (
                      <tr key={gruppo} className="border-b border-slate-100">
                        <td className="px-4 py-2 text-slate-600">{gruppo}</td>
                        <td
                          className={`px-4 py-2 text-right font-mono ${
                            valore >= 0 ? "text-emerald-700" : "text-red-600"
                          }`}
                        >
                          {fmtEuro(valore)}
                        </td>
                      </tr>
                    ))}
                    <tr className="border-b border-slate-100 bg-slate-50">
                      <td className="px-4 py-2 text-slate-500">Ammortamenti</td>
                      <td className="px-4 py-2 text-right font-mono text-red-600">
                        -{fmtEuro(bilancio.conto_economico.totale_ammortamenti)}
                      </td>
                    </tr>
                    <tr className="font-semibold">
                      <td className="px-4 py-2 text-slate-800">Risultato</td>
                      <td
                        className={`px-4 py-2 text-right font-mono ${
                          bilancio.conto_economico.risultato >= 0 ? "text-emerald-700" : "text-red-600"
                        }`}
                      >
                        {fmtEuro(bilancio.conto_economico.risultato)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <h2 className="text-sm font-semibold text-slate-600 mt-6 mb-3">
                Stato Patrimoniale semplificato
              </h2>
              <div className="grid grid-cols-2 gap-4">
                <Card
                  title="Liquidità totale"
                  value={fmtEuro(bilancio.stato_patrimoniale_semplificato.totale_liquidita)}
                />
                <Card
                  title="Immobilizzazioni nette (Cespiti)"
                  value={fmtEuro(bilancio.stato_patrimoniale_semplificato.immobilizzazioni_nette)}
                />
              </div>

              <p className="text-xs text-slate-400 mt-3">{bilancio.nota}</p>
            </section>
          )}

          {tabAttiva === "previsione" && previsione && (
            <section>
              <h2 className="text-sm font-semibold text-slate-600 mb-3">Previsione di cassa</h2>
              {previsione.proiezione.length === 0 ? (
                <p className="text-sm text-slate-500">{previsione.narrazione}</p>
              ) : (
                <>
                  {previsione.avviso && (
                    <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2 mb-3">
                      ⚠ {previsione.avviso}
                    </p>
                  )}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                    <Card title="Liquidità attuale" value={fmtEuro(previsione.liquidita_attuale)} />
                    <Card
                      title="Flusso medio mensile"
                      value={fmtEuro(previsione.flusso_medio_mensile)}
                    />
                    {previsione.proiezione.map((p) => (
                      <Card key={p.periodo} title={p.periodo} value={fmtEuro(p.liquidita_stimata)} />
                    ))}
                  </div>
                  <div className="bg-white border border-slate-200 rounded-lg p-4">
                    <p className="text-sm text-slate-600 leading-relaxed">{previsione.narrazione}</p>
                  </div>
                  <p className="text-xs text-slate-400 mt-3">
                    Proiezione lineare dal flusso di cassa netto medio degli ultimi{" "}
                    {previsione.mesi_storico_usati} mesi con movimenti reali (fino a{" "}
                    {previsione.periodo_riferimento}) — non un modello predittivo, una stima
                    verificabile su dati reali. Non tiene conto di eventi non ricorrenti attesi
                    (una fattura grande in arrivo, una spesa straordinaria pianificata).
                  </p>
                </>
              )}
            </section>
          )}

          {tabAttiva === "iva" && iva && iva.profilo === "arca" && (
            <section>
              <h2 className="text-sm font-semibold text-slate-600 mb-3">IVA — liquidazioni {periodoArca}</h2>
              {iva.periodi.length === 0 ? (
                <p className="text-sm text-slate-500">Nessuna liquidazione IVA ancora per questo esercizio.</p>
              ) : (
              <div className="bg-white border border-slate-200 rounded-lg overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-slate-500 text-xs">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Periodo</th>
                      <th className="px-3 py-2 text-right font-medium">Esigibile</th>
                      <th className="px-3 py-2 text-right font-medium">Detratta</th>
                      <th className="px-3 py-2 text-right font-medium">Saldo</th>
                      <th className="px-3 py-2 text-right font-medium">Dovuta</th>
                    </tr>
                  </thead>
                  <tbody>
                    {iva.periodi.map((p) => (
                      <tr key={p.periodo} className="border-t border-slate-100">
                        <td className="px-3 py-2">{p.periodo === 0 ? "Riepilogo annuale" : `Periodo ${p.periodo}`}</td>
                        <td className="px-3 py-2 text-right font-mono">{fmtEuro(p.iva_esigibile)}</td>
                        <td className="px-3 py-2 text-right font-mono">{fmtEuro(p.iva_detratta)}</td>
                        <td className="px-3 py-2 text-right font-mono">{fmtEuro(p.saldo_periodo)}</td>
                        <td className="px-3 py-2 text-right font-mono">{fmtEuro(p.iva_dovuta)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              )}
              <p className="text-xs text-slate-400 mt-2">{iva.nota}</p>
            </section>
          )}

          {tabAttiva === "iva" && iva && iva.profilo !== "arca" && (
            <section>
              <h2 className="text-sm font-semibold text-slate-600 mb-3">IVA {anno}</h2>
              <div className="grid grid-cols-3 gap-4">
                <Card title="A debito" value={fmtEuro(iva.iva_a_debito)} />
                <Card title="A credito" value={fmtEuro(iva.iva_a_credito)} />
                <Card title="Saldo" value={fmtEuro(iva.saldo_iva)} />
              </div>
            </section>
          )}

          {tabAttiva === "ammortamenti" && ammortamenti && (
            <section>
              <h2 className="text-sm font-semibold text-slate-600 mb-3">
                Cespiti e ammortamenti {ammortamenti.anno}
              </h2>
              <div className="grid grid-cols-2 gap-4 mb-3">
                <Card title="Quota annua stimata" value={fmtEuro(ammortamenti.totale_quota_annua_stimata)} />
                <Card title="Valore netto attuale" value={fmtEuro(ammortamenti.totale_valore_netto_attuale)} />
              </div>
              <div className="bg-white border border-slate-200 rounded-lg overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-slate-500 text-xs">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Cespite</th>
                      <th className="px-3 py-2 text-right font-medium">Valore acquisto</th>
                      <th className="px-3 py-2 text-right font-medium">% amm.</th>
                      <th className="px-3 py-2 text-right font-medium">Quota stimata</th>
                      <th className="px-3 py-2 text-right font-medium">Fondo attuale</th>
                      <th className="px-3 py-2 text-right font-medium">Valore netto</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ammortamenti.cespiti.map((c) => (
                      <tr key={c.codice} className={`border-t border-slate-100 ${c.dismesso ? "opacity-40" : ""}`}>
                        <td className="px-3 py-2">
                          {c.descrizione}
                          {c.dismesso && <span className="text-xs text-slate-400 ml-1">(dismesso)</span>}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">{fmtEuro(c.valore_acquisto)}</td>
                        <td className="px-3 py-2 text-right font-mono">{c.percentuale_ammortamento}%</td>
                        <td className="px-3 py-2 text-right font-mono">{fmtEuro(c.quota_annua_stimata)}</td>
                        <td className="px-3 py-2 text-right font-mono">{fmtEuro(c.fondo_ammortamento_attuale)}</td>
                        <td className="px-3 py-2 text-right font-mono">{fmtEuro(c.valore_netto_attuale)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-slate-400 mt-2">{ammortamenti.nota}</p>
            </section>
          )}

          {tabAttiva === "budget" && budget && (
            <section>
              <h2 className="text-sm font-semibold text-slate-600 mb-3">
                Budget — {mese}/{anno}
              </h2>
              {budget.categorie.length === 0 ? (
                <p className="text-sm text-slate-500">Nessuna soglia di budget impostata ancora.</p>
              ) : (
                <div className="bg-white border border-slate-200 rounded-lg divide-y divide-slate-100">
                  {budget.categorie.map((riga) => (
                    <div key={riga.categoria_codice} className="px-4 py-3">
                      <div className="flex justify-between text-sm mb-1">
                        <span className="text-slate-700 font-medium">{riga.categoria_codice}</span>
                        <span
                          className={
                            riga.livello === "superato"
                              ? "text-red-600"
                              : riga.livello === "in avvicinamento"
                                ? "text-amber-600"
                                : "text-slate-500"
                          }
                        >
                          {fmtEuro(riga.speso)} / {fmtEuro(riga.soglia_mensile)} ({riga.percentuale}%)
                        </span>
                      </div>
                      <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                        <div
                          className={`h-full ${
                            riga.livello === "superato"
                              ? "bg-red-500"
                              : riga.livello === "in avvicinamento"
                                ? "bg-amber-500"
                                : "bg-emerald-500"
                          }`}
                          style={{ width: `${Math.min(riga.percentuale, 100)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}

          {tabAttiva === "anomalie" && anomalie && (
            <section>
              <h2 className="text-sm font-semibold text-slate-600 mb-3">Anomalie rilevate</h2>
              {anomalie.length === 0 ? (
                <p className="text-sm text-slate-500">Nessuna anomalia statistica rilevata al momento.</p>
              ) : (
                <div className="space-y-2">
                  {anomalie.map((a) => (
                    <div
                      key={a.categoria_codice}
                      className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm"
                    >
                      <AlertTriangle size={16} className="text-amber-600 mt-0.5" aria-hidden="true" />
                      <span>
                        <strong>{a.categoria_codice}</strong>: {fmtEuro(a.spesa_mese_corrente)} questo mese,
                        contro una media storica di {fmtEuro(a.media_storica)} (scostamento {a.scostamento}σ).
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}

          {tabAttiva === "riconciliazione" && profilo === "sampeyre" && (
            <section>
              <h2 className="text-sm font-semibold text-slate-600 mb-3">Riconciliazione bancaria</h2>
              <p className="text-xs text-slate-500 mb-3">
                Carica un CSV dell'estratto conto (colonne data/importo/descrizione, nomi flessibili) per
                abbinarlo ai movimenti già registrati su conto Banca. Vengono segnalate solo le differenze.
              </p>

              <form onSubmit={caricaEstrattoConto} className="flex flex-wrap items-center gap-3 mb-4">
                <input
                  type="file"
                  accept=".csv"
                  onChange={(e) => setFileRiconciliazione(e.target.files?.[0] ?? null)}
                  className="text-sm"
                />
                <button
                  type="submit"
                  disabled={!fileRiconciliazione || riconciliando}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-slate-800 text-white text-sm font-medium disabled:opacity-50"
                >
                  <Upload size={14} aria-hidden="true" />
                  {riconciliando ? "Abbinamento..." : "Carica e abbina"}
                </button>
              </form>

              {erroreRiconciliazione && <p className="text-sm text-red-600 mb-3">{erroreRiconciliazione}</p>}

              {riconciliazione && (
                <div className="space-y-4">
                  <div>
                    <h3 className="text-xs font-semibold text-emerald-700 mb-2 flex items-center gap-1">
                      <CheckCircle2 size={14} aria-hidden="true" />
                      Abbinati automaticamente ({riconciliazione.abbinati.length})
                    </h3>
                    {riconciliazione.abbinati.length === 0 ? (
                      <p className="text-xs text-slate-400">Nessun abbinamento trovato.</p>
                    ) : (
                      <div className="bg-white border border-slate-200 rounded-lg divide-y divide-slate-100">
                        {riconciliazione.abbinati.map((a, i) => (
                          <div key={i} className="px-4 py-2 text-xs flex justify-between">
                            <span>
                              {a.movimento.data} — {a.movimento.descrizione} ({a.movimento.categoria_codice})
                            </span>
                            <span className="font-mono text-emerald-700">{fmtEuro(a.movimento.importo)}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div>
                    <h3 className="text-xs font-semibold text-amber-700 mb-2 flex items-center gap-1">
                      <HelpCircle size={14} aria-hidden="true" />
                      Nell'estratto ma non in Prima Nota ({riconciliazione.solo_estratto.length})
                    </h3>
                    {riconciliazione.solo_estratto.length === 0 ? (
                      <p className="text-xs text-slate-400">Nessuna riga senza corrispondenza.</p>
                    ) : (
                      <div className="bg-amber-50 border border-amber-200 rounded-lg divide-y divide-amber-100">
                        {riconciliazione.solo_estratto.map((r, i) => (
                          <div key={i} className="px-4 py-2 text-xs flex justify-between">
                            <span>
                              {r.data} — {r.descrizione}
                            </span>
                            <span className="font-mono">{fmtEuro(r.importo)}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div>
                    <h3 className="text-xs font-semibold text-amber-700 mb-2 flex items-center gap-1">
                      <HelpCircle size={14} aria-hidden="true" />
                      In Prima Nota ma non nell'estratto ({riconciliazione.solo_movimenti.length})
                    </h3>
                    {riconciliazione.solo_movimenti.length === 0 ? (
                      <p className="text-xs text-slate-400">Nessun movimento senza corrispondenza.</p>
                    ) : (
                      <div className="bg-amber-50 border border-amber-200 rounded-lg divide-y divide-amber-100">
                        {riconciliazione.solo_movimenti.map((m) => (
                          <div key={m.id} className="px-4 py-2 text-xs flex justify-between">
                            <span>
                              {m.data} — {m.descrizione} ({m.categoria_codice})
                            </span>
                            <span className="font-mono">{fmtEuro(m.importo)}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </section>
          )}
        </main>
      </div>
    </div>
  );
}
