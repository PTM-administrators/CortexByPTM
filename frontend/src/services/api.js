// Configurazione Axios centralizzata per le chiamate al backend.
import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "/api",
  // Senza un timeout esplicito Axios aspetta all'infinito: se la connessione
  // al database esterno cade a metà richiesta (container riavviato, pool di
  // connessioni esaurito, rete che si blocca) l'utente resta davanti a un
  // caricamento che non finisce mai né dà errore. 45s è abbondante rispetto
  // al caso più lento misurato finora (~20s, reflection a freddo di una
  // tabella larga senza cache — vedi services/db_engine.py) ma comunque
  // limitato: oltre quella soglia è un problema reale, non solo lentezza.
  timeout: 45000,
});

// Allega il JWT Token (se presente) a ogni richiesta in uscita.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("cortex_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Se il token non è più valido, forza il logout lato client.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("cortex_token");
    }
    return Promise.reject(error);
  }
);

// Scarica un file binario (Excel/PDF) da un endpoint protetto: un <a href>
// semplice non porterebbe il token JWT (va nell'header, non nell'URL), quindi
// si passa da Axios con responseType "blob" e si simula il click su un link
// temporaneo — stesso schema per qualunque export del backend.
export async function scaricaFile(url, nomeFileRicadutaSenzaHeader) {
  const res = await api.get(url, { responseType: "blob" });
  const intestazione = res.headers["content-disposition"] || "";
  const corrispondenza = intestazione.match(/filename\*?=(?:UTF-8'')?"?([^;"]+)"?/i);
  const nomeFile = corrispondenza ? decodeURIComponent(corrispondenza[1]) : nomeFileRicadutaSenzaHeader;

  const blobUrl = URL.createObjectURL(res.data);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = nomeFile;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(blobUrl);
}

export default api;
