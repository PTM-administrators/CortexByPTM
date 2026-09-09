// Il router principale che decide cosa mostrare in base allo stato di autenticazione.
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./context/AuthContext";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import Portfolio from "./pages/Portfolio";
import Integrations from "./pages/Integrations";
import DataExplorer from "./pages/DataExplorer";
import Andamenti from "./pages/Andamenti";
import Contabilita from "./pages/Contabilita";
import Team from "./pages/Team";
import Viste from "./pages/Viste";
import Segnalazioni from "./pages/Segnalazioni";

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();

  if (loading) {
    return <div className="min-h-screen flex items-center justify-center text-slate-500">Caricamento...</div>;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <Dashboard />
          </ProtectedRoute>
        }
      />
      <Route
        path="/portfolio"
        element={
          <ProtectedRoute>
            <Portfolio />
          </ProtectedRoute>
        }
      />
      <Route
        path="/integrations"
        element={
          <ProtectedRoute>
            <Integrations />
          </ProtectedRoute>
        }
      />
      <Route
        path="/data"
        element={
          <ProtectedRoute>
            <DataExplorer />
          </ProtectedRoute>
        }
      />
      <Route
        path="/andamenti"
        element={
          <ProtectedRoute>
            <Andamenti />
          </ProtectedRoute>
        }
      />
      <Route
        path="/contabilita"
        element={
          <ProtectedRoute>
            <Contabilita />
          </ProtectedRoute>
        }
      />
      <Route
        path="/team"
        element={
          <ProtectedRoute>
            <Team />
          </ProtectedRoute>
        }
      />
      <Route
        path="/viste"
        element={
          <ProtectedRoute>
            <Viste />
          </ProtectedRoute>
        }
      />
      <Route
        path="/segnalazioni"
        element={
          <ProtectedRoute>
            <Segnalazioni />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
