// Righetta di "chip" cliccabili che inseriscono {{colonna}} in un campo di
// testo con un click — sostituisce l'istruzione "usa {{nome_colonna}}"
// (sintassi da programmatore) con qualcosa che chi non ha mai scritto una
// riga di codice può usare senza doverla imparare. Feedback dell'utente,
// 3 settembre 2026: Viste e Segnalazioni "troppo difficili da usare".
export default function InserisciCampo({ colonne, onInsert, etichetta = "Inserisci un valore:" }) {
  if (!colonne || colonne.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
      <span className="text-xs text-slate-400">{etichetta}</span>
      {colonne.map((c) => (
        <button
          key={c}
          type="button"
          onClick={() => onInsert(c)}
          className="text-xs px-2 py-0.5 rounded-full bg-slate-100 hover:bg-slate-200 text-slate-600 font-mono"
        >
          {c}
        </button>
      ))}
    </div>
  );
}
