// I miei clienti: un colpo d'occhio su tutte le aziende a cui questo utente
// ha accesso (vedi api/auth.py, Membership) — non solo quella attiva. Per
// chi segue più clienti diversi (alcuni con un gestionale vero come Arca,
// altri senza nulla) invece di dover fare un login separato per ognuno.
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Building, ArrowRight, BellRing, Plus, UserPlus } from "lucide-react";
import Sidebar from "../components/layout/Sidebar";
import Topbar from "../components/layout/Topbar";
import { useAuth } from "../context/AuthContext";
import api from "../services/api";

function fmtEuro(value) {
  return new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(value ?? 0);
}

export default function Portfolio() {
  const { organizations, switchOrganization, reloadOrganizations } = useAuth();
  const navigate = useNavigate();
  // Il menu nasconde questa pagina per chi ha una sola azienda (vedi
  // Sidebar.jsx) — ma resta raggiungibile da un link diretto, e per quel
  // caso non ha senso il linguaggio da "portfolio clienti": chi ha
  // un'unica azienda non ha "clienti", ha la propria azienda. Feedback
  // dell'utente, 3 settembre 2026: "così è troppo troppo difficile da usare".
  const haPiuAziende = organizations.length > 1;

  const [aziende, setAziende] = useState(null);
  const [error, setError] = useState("");

  const [inviteCode, setInviteCode] = useState("");
  const [unendo, setUnendo] = useState(false);
  const [erroreInvito, setErroreInvito] = useState("");

  const [mostraCrea, setMostraCrea] = useState(false);
  const [nomeNuova, setNomeNuova] = useState("");
  const [creando, setCreando] = useState(false);
  const [erroreCrea, setErroreCrea] = useState("");

  function caricaPortfolio() {
    api
      .get("/dashboard/portfolio")
      .then((res) => setAziende(res.data))
      .catch(() => setError("Impossibile caricare l'elenco delle aziende."));
  }

  useEffect(() => {
    caricaPortfolio();
  }, []);

  async function vaiAllAzienda(organizationId) {
    await switchOrganization(organizationId);
    navigate("/dashboard");
  }

  async function unisciti(e) {
    e.preventDefault();
    setErroreInvito("");
    setUnendo(true);
    try {
      await api.post("/auth/join-organization", { invite_code: inviteCode });
      setInviteCode("");
      await reloadOrganizations();
      caricaPortfolio();
    } catch (err) {
      setErroreInvito(err.response?.data?.detail ?? "Codice invito non valido.");
    } finally {
      setUnendo(false);
    }
  }

  async function creaAzienda(e) {
    e.preventDefault();
    setErroreCrea("");
    setCreando(true);
    try {
      await api.post("/auth/create-organization", { company_name: nomeNuova });
      setNomeNuova("");
      setMostraCrea(false);
      await reloadOrganizations();
      caricaPortfolio();
    } catch (err) {
      setErroreCrea(err.response?.data?.detail ?? "Impossibile creare l'azienda.");
    } finally {
      setCreando(false);
    }
  }

  return (
    <div className="flex">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Topbar />
        <main className="p-6 flex-1 space-y-6 max-w-4xl">
          <div className="flex items-center gap-2">
            <Building size={20} className="text-slate-400" aria-hidden="true" />
            <h1 className="text-lg font-semibold text-slate-800">
              {haPiuAziende ? "I miei clienti" : "Segui un'altra azienda"}
            </h1>
          </div>
          <p className="text-sm text-slate-500 -mt-4">
            {haPiuAziende
              ? "Tutte le aziende a cui hai accesso con questo account, in un colpo d'occhio — clicca su un'azienda per passare a lavorare su di lei."
              : "Il tuo account è collegato solo alla tua azienda. Se segui anche altre aziende come consulente (o vuoi aggiungerne una nuova), fallo da qui."}
          </p>

          {error && <p className="text-sm text-red-600">{error}</p>}

          {haPiuAziende && <div className="space-y-3">
            {aziende === null && <p className="text-sm text-slate-500">Caricamento...</p>}
            {aziende?.map((a) => (
              <div
                key={a.organization_id}
                className={`bg-white border rounded-lg p-4 ${
                  a.e_azienda_attiva ? "border-slate-800" : "border-slate-200"
                }`}
              >
                <div className="flex items-start justify-between gap-4 flex-wrap">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-sm font-semibold text-slate-800">{a.company_name}</h2>
                      {a.e_azienda_attiva && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-white">
                          attiva ora
                        </span>
                      )}
                      <span className="text-xs text-slate-400">{a.industry_label}</span>
                    </div>

                    {a.riepilogo_finanziario ? (
                      <div className="mt-2 space-y-1">
                        <p className="text-sm text-slate-700">
                          Liquidità: <strong>{fmtEuro(a.riepilogo_finanziario.totale_liquidita)}</strong>
                        </p>
                        {a.riepilogo_finanziario.narrazione && (
                          <p className="text-xs text-slate-500 max-w-xl">
                            {a.riepilogo_finanziario.narrazione}
                          </p>
                        )}
                      </div>
                    ) : (
                      <p className="mt-2 text-xs text-slate-400">
                        Nessun database contabile collegato ancora.
                      </p>
                    )}

                    {a.segnalazioni_aperte > 0 && (
                      <p className="mt-2 flex items-center gap-1 text-xs font-medium text-amber-700">
                        <BellRing size={12} aria-hidden="true" />
                        {a.segnalazioni_aperte} segnalazion{a.segnalazioni_aperte === 1 ? "e" : "i"} aperte
                      </p>
                    )}
                  </div>

                  {!a.e_azienda_attiva && (
                    <button
                      onClick={() => vaiAllAzienda(a.organization_id)}
                      className="flex items-center gap-1 text-xs font-medium px-3 py-1.5 rounded-md bg-slate-800 text-white shrink-0"
                    >
                      Vai a questa azienda <ArrowRight size={12} aria-hidden="true" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-white border border-slate-200 rounded-lg p-4">
              <h2 className="text-sm font-semibold text-slate-600 mb-2 flex items-center gap-1.5">
                <UserPlus size={14} aria-hidden="true" /> Aggiungi un'azienda esistente
              </h2>
              <p className="text-xs text-slate-400 mb-3">
                Con il codice invito che quell'azienda ti ha condiviso (pagina Team di quell'azienda).
              </p>
              <form onSubmit={unisciti} className="flex gap-2">
                <input
                  value={inviteCode}
                  onChange={(e) => setInviteCode(e.target.value)}
                  placeholder="Codice invito"
                  required
                  className="flex-1 border border-slate-300 rounded-md px-3 py-2 text-sm"
                />
                <button
                  type="submit"
                  disabled={unendo}
                  className="px-3 py-2 rounded-md bg-slate-800 text-white text-sm font-medium disabled:opacity-50"
                >
                  {unendo ? "..." : "Unisciti"}
                </button>
              </form>
              {erroreInvito && <p className="text-xs text-red-600 mt-2">{erroreInvito}</p>}
            </div>

            <div className="bg-white border border-slate-200 rounded-lg p-4">
              <h2 className="text-sm font-semibold text-slate-600 mb-2 flex items-center gap-1.5">
                <Plus size={14} aria-hidden="true" /> Nuova azienda
              </h2>
              <p className="text-xs text-slate-400 mb-3">
                Crea un'azienda nuova da seguire, restando collegato con questo account.
              </p>
              {mostraCrea ? (
                <form onSubmit={creaAzienda} className="flex gap-2">
                  <input
                    value={nomeNuova}
                    onChange={(e) => setNomeNuova(e.target.value)}
                    placeholder="Nome azienda"
                    required
                    className="flex-1 border border-slate-300 rounded-md px-3 py-2 text-sm"
                  />
                  <button
                    type="submit"
                    disabled={creando}
                    className="px-3 py-2 rounded-md bg-slate-800 text-white text-sm font-medium disabled:opacity-50"
                  >
                    {creando ? "..." : "Crea"}
                  </button>
                </form>
              ) : (
                <button
                  onClick={() => setMostraCrea(true)}
                  className="px-3 py-2 rounded-md bg-slate-100 text-slate-700 text-sm font-medium"
                >
                  Nuova azienda
                </button>
              )}
              {erroreCrea && <p className="text-xs text-red-600 mt-2">{erroreCrea}</p>}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
