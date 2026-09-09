// Schermata di Login.
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      navigate("/dashboard");
    } catch {
      setError("Email o password non corrette.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <form onSubmit={handleSubmit} className="bg-white shadow-sm border border-slate-200 rounded-lg p-8 w-full max-w-sm">
        <h1 className="text-xl font-bold text-slate-800 mb-6">Accedi a Cortex Enterprise</h1>

        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

        <label className="block text-sm text-slate-600 mb-1">Email</label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          className="w-full border border-slate-300 rounded-md px-3 py-2 mb-4 text-sm"
        />

        <label className="block text-sm text-slate-600 mb-1">Password</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          className="w-full border border-slate-300 rounded-md px-3 py-2 mb-6 text-sm"
        />

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-slate-800 text-white rounded-md py-2 text-sm font-medium disabled:opacity-50"
        >
          {loading ? "Accesso in corso..." : "Accedi"}
        </button>

        <p className="text-sm text-slate-500 mt-4 text-center">
          Non hai un account? <Link to="/register" className="text-slate-800 font-medium">Registrati</Link>
        </p>
      </form>
    </div>
  );
}
