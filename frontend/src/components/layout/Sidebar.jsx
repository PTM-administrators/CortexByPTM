// Menu laterale dinamico: le voci arrivano da /api/dashboard (industry_rules.py
// sul backend), non da un array fisso — impostare `industry` in fase di
// registrazione basta a cambiare cosa vede l'utente qui, senza toccare questo file.
import { NavLink } from "react-router-dom";
import * as Icons from "lucide-react";
import { useAuth } from "../../context/AuthContext";

// Fallback se il backend manda un nome icona non presente in lucide-react
// (es. refuso in industry_rules.py): meglio un'icona generica che una pagina rotta.
function NavIcon({ name, ...props }) {
  const Icon = Icons[name] || Icons.Circle;
  return <Icon {...props} />;
}

export default function Sidebar() {
  const { user, industryConfig, organizations } = useAuth();
  const BrandIcon = Icons[industryConfig.industry_icon] || Icons.LayoutGrid;

  // "I miei clienti" parla la lingua di chi segue più aziende come
  // consulente (vedi Portfolio.jsx) — mostrata a tutti anche a chi ha una
  // sola azienda, il caso comune, non aveva senso ("i tuoi clienti" quando
  // l'unica azienda in elenco sei tu stesso). Feedback dell'utente, 3
  // settembre 2026: "così è troppo troppo difficile da usare".
  const navItems = industryConfig.nav_items.filter(
    (item) => item.to !== "/portfolio" || organizations.length > 1
  );

  return (
    <aside className="w-60 h-screen sticky top-0 bg-slate-900 text-slate-100 flex flex-col p-4">
      <div className="flex items-center gap-2 text-xl font-bold mb-8">
        <BrandIcon size={22} className="text-slate-300" aria-hidden="true" />
        Cortex Enterprise
      </div>

      <nav className="flex flex-col gap-2">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium ${
                isActive ? "bg-slate-700" : "hover:bg-slate-800"
              }`
            }
          >
            <NavIcon name={item.icon} size={18} aria-hidden="true" />
            {item.label}
          </NavLink>
        ))}
      </nav>

      {user && (
        <div className="mt-auto text-xs text-slate-400">
          Settore: {industryConfig.industry_label || user.industry}
        </div>
      )}
    </aside>
  );
}
