// Barra superiore: mostra l'utente collegato, il selettore azienda (se ne ha
// più di una — vedi AuthContext.organizations) e il pulsante di logout.
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";

export default function Topbar() {
  const { user, organizations, switchOrganization, logout } = useAuth();
  const navigate = useNavigate();

  async function handleSwitch(e) {
    const organizationId = Number(e.target.value);
    if (organizationId === undefined || Number.isNaN(organizationId)) return;
    await switchOrganization(organizationId);
    navigate("/dashboard");
  }

  return (
    <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-6">
      {organizations.length > 1 ? (
        <select
          value={user?.organization_id ?? ""}
          onChange={handleSwitch}
          className="font-semibold text-slate-800 border border-slate-200 rounded-md px-2 py-1.5 text-sm bg-white"
        >
          {organizations.map((o) => (
            <option key={o.id} value={o.id}>
              {o.company_name}
            </option>
          ))}
        </select>
      ) : (
        <div className="font-semibold text-slate-800">{user?.company_name ?? "—"}</div>
      )}
      <div className="flex items-center gap-4">
        {user?.role === "readonly" && (
          <span
            title="Puoi consultare tutto ma non configurare integrazioni, segnalazioni, viste o team — chiedi a un amministratore di promuoverti dalla pagina Team se serve."
            className="text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2.5 py-1"
          >
            Sola lettura
          </span>
        )}
        <span className="text-sm text-slate-500">{user?.email}</span>
        <button
          onClick={logout}
          className="text-sm px-3 py-1.5 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-700"
        >
          Esci
        </button>
      </div>
    </header>
  );
}
