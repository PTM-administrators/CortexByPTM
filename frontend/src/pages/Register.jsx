// Schermata di Registrazione: crea una nuova azienda (con settore associato)
// oppure si unisce a un'azienda già esistente con un codice invito, diventando
// un ulteriore amministratore con accesso agli stessi dati (vedi Team.jsx).
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

// Tenuto in sync a mano con le chiavi di INDUSTRY_RULES in
// backend/app/services/industry_rules.py (stesso value, stessa label).
const INDUSTRIES = [
  { value: "generic", label: "Generico" },
  { value: "ecommerce", label: "E-commerce" },
  { value: "real_estate", label: "Immobiliare" },
  { value: "professional_services", label: "Servizi Professionali" },
  { value: "nonprofit_finance", label: "Finanza No-Profit" },
];

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [modalita, setModalita] = useState("nuova_azienda"); // "nuova_azienda" | "invito"
  const [form, setForm] = useState({
    company_name: "",
    email: "",
    password: "",
    industry: "generic",
    invite_code: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function handleChange(e) {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const payload =
        modalita === "invito"
          ? { email: form.email, password: form.password, invite_code: form.invite_code }
          : {
              email: form.email,
              password: form.password,
              company_name: form.company_name,
              industry: form.industry,
            };
      await register(payload);
      navigate("/dashboard");
    } catch (err) {
      setError(err.response?.data?.detail ?? "Impossibile completare la registrazione. Controlla i dati inseriti.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <form onSubmit={handleSubmit} className="bg-white shadow-sm border border-slate-200 rounded-lg p-8 w-full max-w-sm">
        <h1 className="text-xl font-bold text-slate-800 mb-2">Crea il tuo account</h1>

        <div className="flex gap-1 bg-slate-100 rounded-md p-1 mb-6 text-sm">
          <button
            type="button"
            onClick={() => setModalita("nuova_azienda")}
            className={`flex-1 rounded py-1.5 font-medium ${
              modalita === "nuova_azienda" ? "bg-white shadow-sm text-slate-800" : "text-slate-500"
            }`}
          >
            Nuova azienda
          </button>
          <button
            type="button"
            onClick={() => setModalita("invito")}
            className={`flex-1 rounded py-1.5 font-medium ${
              modalita === "invito" ? "bg-white shadow-sm text-slate-800" : "text-slate-500"
            }`}
          >
            Ho un invito
          </button>
        </div>

        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

        {modalita === "invito" && (
          <>
            <label className="block text-sm text-slate-600 mb-1">Codice invito</label>
            <input
              name="invite_code"
              value={form.invite_code}
              onChange={handleChange}
              required
              placeholder="Chiedilo a un amministratore della tua azienda"
              className="w-full border border-slate-300 rounded-md px-3 py-2 mb-4 text-sm"
            />
          </>
        )}

        {modalita === "nuova_azienda" && (
          <>
            <label className="block text-sm text-slate-600 mb-1">Nome azienda</label>
            <input
              name="company_name"
              value={form.company_name}
              onChange={handleChange}
              required
              className="w-full border border-slate-300 rounded-md px-3 py-2 mb-4 text-sm"
            />
          </>
        )}

        <label className="block text-sm text-slate-600 mb-1">Email</label>
        <input
          type="email"
          name="email"
          value={form.email}
          onChange={handleChange}
          required
          className="w-full border border-slate-300 rounded-md px-3 py-2 mb-4 text-sm"
        />

        <label className="block text-sm text-slate-600 mb-1">Password</label>
        <input
          type="password"
          name="password"
          value={form.password}
          onChange={handleChange}
          required
          className="w-full border border-slate-300 rounded-md px-3 py-2 mb-4 text-sm"
        />

        {modalita === "nuova_azienda" && (
          <>
            <label className="block text-sm text-slate-600 mb-1">Settore</label>
            <select
              name="industry"
              value={form.industry}
              onChange={handleChange}
              className="w-full border border-slate-300 rounded-md px-3 py-2 mb-6 text-sm"
            >
              {INDUSTRIES.map((ind) => (
                <option key={ind.value} value={ind.value}>
                  {ind.label}
                </option>
              ))}
            </select>
          </>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-slate-800 text-white rounded-md py-2 text-sm font-medium disabled:opacity-50 mt-2"
        >
          {loading ? "Creazione in corso..." : "Registrati"}
        </button>

        <p className="text-sm text-slate-500 mt-4 text-center">
          Hai già un account? <Link to="/login" className="text-slate-800 font-medium">Accedi</Link>
        </p>
      </form>
    </div>
  );
}
