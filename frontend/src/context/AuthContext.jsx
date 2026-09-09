// Ricorda chi è loggato, che settore (industry) ha e come si deve adattare la UI
// per quel settore (menu, icone), condividendolo in tutta l'app.
import { createContext, useContext, useEffect, useState } from "react";
import api from "../services/api";

const AuthContext = createContext(null);

// Configurazione di fallback finché /api/dashboard non ha ancora risposto,
// così Sidebar ha sempre qualcosa da renderizzare senza dover gestire "null".
const FALLBACK_INDUSTRY_CONFIG = {
  industry_label: "",
  industry_icon: "LayoutGrid",
  nav_items: [
    { to: "/dashboard", label: "Dashboard", icon: "LayoutDashboard" },
    { to: "/portfolio", label: "I miei clienti", icon: "Building" },
    { to: "/integrations", label: "Integrazioni", icon: "Plug" },
    { to: "/data", label: "Dati", icon: "Database" },
    { to: "/andamenti", label: "Andamenti", icon: "TrendingUp" },
    { to: "/team", label: "Team", icon: "Users" },
    { to: "/viste", label: "Viste", icon: "LayoutTemplate" },
  ],
};

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [industryConfig, setIndustryConfig] = useState(FALLBACK_INDUSTRY_CONFIG);
  // Tutte le aziende a cui l'utente ha accesso (non solo quella attiva) —
  // chi segue più clienti diversi (vedi api/auth.py, Membership) le cambia
  // dal selettore in Topbar invece di fare login separati per ognuna.
  const [organizations, setOrganizations] = useState([]);
  const [loading, setLoading] = useState(true);

  // Carica la configurazione UI del settore (menu dinamico, icone): stesso
  // endpoint usato dalla Dashboard per widget/stats, chiamato qui una volta
  // sola così anche la Sidebar (montata su ogni pagina) la trova già pronta.
  async function loadIndustryConfig() {
    try {
      const { data } = await api.get("/dashboard");
      setIndustryConfig(data);
    } catch {
      setIndustryConfig(FALLBACK_INDUSTRY_CONFIG);
    }
  }

  async function loadOrganizations() {
    try {
      const { data } = await api.get("/auth/my-organizations");
      setOrganizations(data);
    } catch {
      setOrganizations([]);
    }
  }

  useEffect(() => {
    const token = localStorage.getItem("cortex_token");
    if (!token) {
      setLoading(false);
      return;
    }

    api
      .get("/auth/me")
      .then((res) => {
        setUser(res.data);
        return Promise.all([loadIndustryConfig(), loadOrganizations()]);
      })
      .catch(() => localStorage.removeItem("cortex_token"))
      .finally(() => setLoading(false));
  }, []);

  async function login(email, password) {
    const form = new URLSearchParams();
    form.append("username", email);
    form.append("password", password);

    const { data } = await api.post("/auth/login", form, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    localStorage.setItem("cortex_token", data.access_token);

    const me = await api.get("/auth/me");
    setUser(me.data);
    await Promise.all([loadIndustryConfig(), loadOrganizations()]);
    return me.data;
  }

  async function register(payload) {
    await api.post("/auth/register", payload);
    return login(payload.email, payload.password);
  }

  function logout() {
    localStorage.removeItem("cortex_token");
    setUser(null);
    setIndustryConfig(FALLBACK_INDUSTRY_CONFIG);
    setOrganizations([]);
  }

  // Cambia l'azienda attiva tra quelle già accessibili — non un login
  // diverso, la stessa sessione guarda dati diversi (vedi
  // api/auth.py.switch_organization). Ricarica anche la config di settore,
  // che dipende dall'azienda ora attiva.
  async function switchOrganization(organizationId) {
    const { data } = await api.post("/auth/switch-organization", { organization_id: organizationId });
    setUser(data);
    await loadIndustryConfig();
    return data;
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        industryConfig,
        organizations,
        loading,
        login,
        register,
        logout,
        switchOrganization,
        reloadOrganizations: loadOrganizations,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth deve essere usato dentro un AuthProvider");
  }
  return context;
}
