// Team: membri della propria azienda (con il loro ruolo) + codice invito per
// aggiungerne altri. Generica per qualunque settore, come Integrazioni/Dati.
//
// Ruoli (3 settembre 2026): chi si unisce con il codice invito parte come
// "sola lettura" — un amministratore esistente lo promuove da qui se deve
// poter configurare integrazioni/segnalazioni/team, non solo consultare
// dashboard/andamenti/contabilità/chat (vedi backend/app/models/membership.py).
import { useEffect, useState } from "react";
import { Users, Copy, RefreshCw, Check, ShieldCheck, Eye } from "lucide-react";
import Sidebar from "../components/layout/Sidebar";
import Topbar from "../components/layout/Topbar";
import api from "../services/api";

export default function Team() {
  const [team, setTeam] = useState(null);
  const [error, setError] = useState("");
  const [copiato, setCopiato] = useState(false);
  const [rigenerando, setRigenerando] = useState(false);
  const [cambiandoRuolo, setCambiandoRuolo] = useState(null); // id della membership in corso di modifica

  useEffect(() => {
    loadTeam();
  }, []);

  function loadTeam() {
    api
      .get("/team")
      .then((res) => setTeam(res.data))
      .catch(() => setError("Impossibile caricare il team."));
  }

  async function copiaCodice() {
    await navigator.clipboard.writeText(team.invite_code);
    setCopiato(true);
    setTimeout(() => setCopiato(false), 2000);
  }

  async function rigeneraCodice() {
    if (!window.confirm("Il codice invito attuale smetterà di funzionare. Continuare?")) return;
    setRigenerando(true);
    try {
      const { data } = await api.post("/team/invite/regenerate");
      setTeam(data);
    } catch {
      setError("Impossibile rigenerare il codice.");
    } finally {
      setRigenerando(false);
    }
  }

  async function cambiaRuolo(membershipId, nuovoRuolo) {
    setError("");
    setCambiandoRuolo(membershipId);
    try {
      const { data } = await api.post(`/team/members/${membershipId}/role`, { role: nuovoRuolo });
      setTeam(data);
    } catch (err) {
      setError(err.response?.data?.detail ?? "Impossibile cambiare il ruolo.");
    } finally {
      setCambiandoRuolo(null);
    }
  }

  const sonoAdmin = team?.ruolo_attivo === "admin";

  return (
    <div className="flex">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Topbar />
        <main className="p-6 flex-1 max-w-2xl space-y-6">
          <div className="flex items-center gap-2">
            <Users size={20} className="text-slate-400" aria-hidden="true" />
            <h1 className="text-lg font-semibold text-slate-800">Team</h1>
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}

          {team && (
            <>
              <section className="bg-white border border-slate-200 rounded-lg p-5">
                <h2 className="text-sm font-semibold text-slate-600 mb-3">
                  Membri di {team.company_name} ({team.members.length})
                </h2>
                <ul className="divide-y divide-slate-100">
                  {team.members.map((m) => (
                    <li key={m.id} className="py-2 flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2 text-sm text-slate-700">
                        {m.role === "admin" ? (
                          <ShieldCheck size={14} className="text-emerald-600 shrink-0" aria-hidden="true" />
                        ) : (
                          <Eye size={14} className="text-slate-400 shrink-0" aria-hidden="true" />
                        )}
                        {m.email}
                      </div>

                      {sonoAdmin ? (
                        <select
                          value={m.role}
                          disabled={cambiandoRuolo === m.id}
                          onChange={(e) => cambiaRuolo(m.id, e.target.value)}
                          className="text-xs border border-slate-300 rounded-md px-2 py-1 bg-white disabled:opacity-50"
                        >
                          <option value="admin">Amministratore</option>
                          <option value="readonly">Sola lettura</option>
                        </select>
                      ) : (
                        <span className="text-xs text-slate-400">
                          {m.role === "admin" ? "Amministratore" : "Sola lettura"}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </section>

              <section className="bg-white border border-slate-200 rounded-lg p-5">
                <h2 className="text-sm font-semibold text-slate-600 mb-2">Invita un nuovo membro</h2>
                <p className="text-xs text-slate-500 mb-3">
                  Nessun limite al numero di membri: condividi questo codice, chi lo usa in fase di registrazione
                  (scheda "Ho un invito") entra come "sola lettura" — può consultare dashboard, andamenti,
                  contabilità e chat, ma non configurare nulla. Promuovilo ad amministratore dall'elenco sopra se
                  deve poter gestire integrazioni, segnalazioni e team.
                </p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 bg-slate-50 border border-slate-200 rounded-md px-3 py-2 text-sm font-mono">
                    {team.invite_code}
                  </code>
                  <button
                    onClick={copiaCodice}
                    aria-label="Copia codice invito"
                    className="p-2 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-700"
                  >
                    {copiato ? <Check size={16} /> : <Copy size={16} />}
                  </button>
                  {sonoAdmin && (
                    <button
                      onClick={rigeneraCodice}
                      disabled={rigenerando}
                      aria-label="Rigenera codice invito"
                      className="p-2 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-700 disabled:opacity-50"
                    >
                      <RefreshCw size={16} />
                    </button>
                  )}
                </div>
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
