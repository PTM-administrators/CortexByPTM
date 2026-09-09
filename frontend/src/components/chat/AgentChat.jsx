// Il box dove l'utente impartisce gli ordini all'agente operativo. Le azioni
// con effetti verso l'esterno (oggi: inviare un'email) non partono da sole:
// l'agente propone una bozza e qui compare un bottone "Conferma invio" prima
// che venga eseguita davvero (POST /agent/confirm/{id}).
//
// Le richieste sui dati (grafici/tabelle/schede) non si disegnano qui: la chat
// resta il comando, `onWidget` porta il risultato alla pagina principale
// (vedi Dashboard.jsx + components/widgets/WidgetCanvas.jsx).
import { useEffect, useState } from "react";
import { HelpCircle, X } from "lucide-react";
import api from "../../services/api";

// Riconoscimento a pattern (StubLLMClient), non un vero LLM: la chat capisce
// solo queste forme, non richieste libere — l'amministratore non ha modo di
// saperlo guardando solo il campo di testo. Organizzato per categoria invece
// che come lista piatta, così si vede a colpo d'occhio "cosa posso chiedere
// sui soldi" vs "cosa posso far fare all'agente".
const CATEGORIE_AIUTO = [
  {
    titolo: "Sui soldi (funziona su qualunque azienda collegata)",
    esempi: [
      "quanto abbiamo in banca?",
      "mostrami le spese di luglio",
      "composizione delle spese di agosto",
      "confronta le spese di luglio con maggio",
      "andamento delle entrate nel 2026",
      "elenco dei movimenti di agosto",
      "perché sono aumentate le spese questo mese?",
      "come sta andando l'azienda? (un quadro completo, non un solo grafico)",
      "e il mese scorso? (dopo una domanda sui soldi, capisce a cosa ti riferisci)",
    ],
  },
  {
    titolo: "Qualunque altro dato collegato",
    esempi: [
      "quanti clienti abbiamo?",
      "quante fatture abbiamo emesso?",
      "quanti fornitori abbiamo?",
      "prova con qualunque parola: se il dato esiste nel database collegato, lo trova da solo",
    ],
  },
  {
    titolo: "Email",
    esempi: ["manda una email a mario@esempio.it dicendo: ciao Mario — ti aspetto le prossime chiavi"],
  },
  {
    titolo: "Ricerca online",
    esempi: ["cerca il numero di telefono del fornitore XY"],
  },
];

export default function AgentChat({ onWidget }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [mostraAiuto, setMostraAiuto] = useState(false);
  // Nomi reali delle Viste salvate di questa azienda: "mostrami [nome]" le
  // richiama solo se il nome esiste davvero — meglio mostrare quelli veri
  // che un esempio generico che potrebbe non applicarsi.
  const [nomiViste, setNomiViste] = useState([]);

  useEffect(() => {
    api
      .get("/views")
      .then((res) => setNomiViste(res.data.map((v) => v.name)))
      .catch(() => setNomiViste([]));
  }, []);

  async function sendMessage(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setSending(true);

    try {
      const { data } = await api.post("/agent/chat", { message: text });
      if (data.widget) onWidget?.(data.widget);
      setMessages((prev) => [
        ...prev,
        {
          role: "agent",
          text: data.reply,
          pendingAction: data.pending_action,
          hasWidget: Boolean(data.widget),
          status: null, // "eseguita" | "annullata" | "errore" dopo la conferma/annullamento
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "agent", text: "Si è verificato un errore, riprova." },
      ]);
    } finally {
      setSending(false);
    }
  }

  async function confirmAction(index, actionId) {
    setMessages((prev) => prev.map((m, i) => (i === index ? { ...m, confirming: true } : m)));
    try {
      const { data } = await api.post(`/agent/confirm/${actionId}`);
      setMessages((prev) =>
        prev.map((m, i) =>
          i === index
            ? { ...m, confirming: false, status: "eseguita", statusText: `Inviata a ${data.detail?.to ?? ""}.` }
            : m
        )
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((m, i) =>
          i === index
            ? {
                ...m,
                confirming: false,
                status: "errore",
                statusText: err.response?.data?.detail ?? "Invio non riuscito.",
              }
            : m
        )
      );
    }
  }

  function cancelAction(index) {
    setMessages((prev) =>
      prev.map((m, i) => (i === index ? { ...m, status: "annullata", statusText: "Invio annullato." } : m))
    );
  }

  return (
    <div className="flex flex-col border border-slate-200 rounded-lg bg-white h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-100">
        <span className="text-xs font-medium text-slate-500">Chiedi all'agente</span>
        <button
          onClick={() => setMostraAiuto((m) => !m)}
          className="flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800"
        >
          {mostraAiuto ? <X size={13} aria-hidden="true" /> : <HelpCircle size={13} aria-hidden="true" />}
          {mostraAiuto ? "Chiudi" : "Cosa posso chiederti?"}
        </button>
      </div>

      {mostraAiuto && (
        <div className="p-4 border-b border-slate-100 bg-slate-50 space-y-3 max-h-64 overflow-y-auto">
          <p className="text-xs text-slate-400">
            L'agente riconosce queste forme di richiesta, e prova anche a cercare qualunque altro dato
            del database collegato — usa nomi di mese reali, un indirizzo email vero, ecc.
          </p>
          {CATEGORIE_AIUTO.map((cat) => (
            <div key={cat.titolo}>
              <div className="text-xs font-semibold text-slate-600 mb-1">{cat.titolo}</div>
              <ul className="space-y-0.5">
                {cat.esempi.map((e) => (
                  <li key={e} className="text-xs text-slate-500 italic">
                    "{e}"
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {nomiViste.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-slate-600 mb-1">Le tue Viste salvate</div>
              <ul className="space-y-0.5">
                {nomiViste.map((n) => (
                  <li key={n} className="text-xs text-slate-500 italic">
                    "mostrami {n}"
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && !mostraAiuto && (
          <p className="text-sm text-slate-400">
            Scrivi un comando per l'agente, ad esempio "manda una email a mario@esempio.it
            dicendo: ciao Mario" oppure "mostrami le spese di luglio confrontate con maggio" — o
            apri "Cosa posso chiederti?" qui sopra per l'elenco completo.
          </p>
        )}
        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`max-w-[85%] px-3 py-2 rounded-lg text-sm ${
              msg.role === "user" ? "ml-auto bg-slate-800 text-white" : "bg-slate-100 text-slate-800"
            }`}
          >
            <div>{msg.text}</div>

            {msg.hasWidget && (
              <div className="mt-1 text-xs text-slate-500 italic">
                ↑ Vista aggiornata nella pagina principale.
              </div>
            )}

            {msg.pendingAction?.tool === "email_tool" && !msg.status && (
              <div className="mt-2 bg-white border border-slate-200 rounded-md p-2 text-xs text-slate-600 space-y-1">
                <div>
                  <strong>A:</strong> {msg.pendingAction.preview.to_address}
                </div>
                <div>
                  <strong>Oggetto:</strong> {msg.pendingAction.preview.subject}
                </div>
                <div>
                  <strong>Testo:</strong> {msg.pendingAction.preview.body}
                </div>
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={() => confirmAction(idx, msg.pendingAction.id)}
                    disabled={msg.confirming}
                    className="px-3 py-1 rounded-md bg-emerald-600 text-white text-xs font-medium disabled:opacity-50"
                  >
                    {msg.confirming ? "Invio..." : "Conferma invio"}
                  </button>
                  <button
                    onClick={() => cancelAction(idx)}
                    disabled={msg.confirming}
                    className="px-3 py-1 rounded-md bg-slate-200 text-slate-700 text-xs font-medium"
                  >
                    Annulla
                  </button>
                </div>
              </div>
            )}

            {msg.status && (
              <div
                className={`mt-2 text-xs ${msg.status === "errore" ? "text-red-600" : "text-emerald-700"}`}
              >
                {msg.statusText}
              </div>
            )}
          </div>
        ))}
      </div>

      <form onSubmit={sendMessage} className="p-3 border-t border-slate-200 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Scrivi un comando..."
          className="flex-1 border border-slate-300 rounded-md px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={sending}
          className="px-4 py-2 rounded-md bg-slate-800 text-white text-sm disabled:opacity-50"
        >
          Invia
        </button>
      </form>
    </div>
  );
}
