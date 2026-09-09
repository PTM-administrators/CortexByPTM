"""
Esplorazione libera dalla chat: risponde a domande su tabelle collegate che
non rientrano nei modi fissi di visualize_tool (saldo/periodo/confronto/...,
pensati solo per i due motori contabili riconosciuti, Sampeyre e Arca).
Prima di questo modulo, qualunque domanda fuori dal dominio entrate/uscite
("quanti fornitori abbiamo?", "quante fatture...") cadeva nel vuoto — la
chat sapeva rispondere solo sui due profili contabili, non su nessun altro
dato dell'azienda (feedback dell'utente, 3 settembre 2026: "la chat è
piuttosto inutile").

Due livelli, dal più ricco al più povero:
1. Tra le tabelle che services.analisi_automatica ha già trovato "interessanti"
   per la pagina Andamenti (hanno una colonna data + una numerica plausibili,
   analisi già fatta e cacheata): risposta più ricca, un vero andamento mensile.
2. Tra TUTTE le tabelle del database collegato, quando nessuna delle
   "interessanti" sembra pertinente: risposta più povera, solo conteggio ed
   eventuale somma di una colonna numerica plausibile — ma pur sempre un dato
   vero, non un vicolo cieco.

Nessuna query libera scritta dall'utente o dall'LLM: il nome della tabella
usato in ogni query viene sempre da list_table_names() (whitelist reale del
database), mai da testo passato direttamente — stessa cautela già in uso in
analisi_automatica._conta_righe.
"""
import re
from typing import Any

from sqlalchemy import inspect, text

from app.services import analisi_automatica, db_engine

# Parole italiane troppo comuni per essere un segnale su QUALE tabella
# cercare — senza questo filtro, "quanti" o "abbiamo" "matcherebbero" quasi
# ogni domanda con la prima tabella che condivide una di queste sillabe.
_STOPWORD = {
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "del", "della", "dei", "degli", "delle",
    "e", "ed", "a", "ad", "in", "con", "su", "per", "tra", "fra", "che", "chi", "cosa", "come", "quanto",
    "quanti", "quanta", "quante", "quale", "quali", "abbiamo", "avete", "hanno", "ci", "sono", "dammi",
    "mostrami", "fammi", "vedere", "nostri", "nostra", "nostro", "questo", "questa", "questi", "queste",
}
_LUNGHEZZA_MINIMA_TOKEN = 4  # sotto, un token è troppo generico per essere un segnale utile (sigle corte incluse)


def _token(testo: str) -> list[str]:
    """Spacca sia su spazi/punteggiatura sia sui confini camelCase/PascalCase
    — i nomi tabella di un ERP reale (Arca) sono in CamelCase, es.
    "CGDatiFatturaR" → ["cg", "dati", "fattura", "r"]. Due regole, non una
    sola: minuscola-poi-maiuscola ("Dati|Fattura") copre la maggior parte
    dei casi, ma non basta per il prefisso-sigla-poi-entità molto comune in
    Arca ("VBCliente", "RAAnagrafe" — tutto maiuscolo fino all'inizio della
    parola vera) dove non esiste nessun confine minuscola→maiuscola. Scoperto
    provando su dati reali: senza la seconda regola, "VBCliente" restava un
    unico token "vbcliente" e "quanti clienti abbiamo?" non trovava mai
    questa tabella, nonostante fosse la risposta giusta."""
    con_sigle_separate = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", testo)
    camel_separato = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", con_sigle_separate)
    grezzi = re.findall(r"[a-zàèéìòù]+", camel_separato.lower())
    return [t for t in grezzi if t not in _STOPWORD and len(t) >= _LUNGHEZZA_MINIMA_TOKEN]


def _radice_comune(a: str, b: str) -> bool:
    """Confronto approssimativo per singolare/plurale e piccole variazioni
    italiane ("fattura"/"fatture", "cliente"/"clienti"): non uno stemmer
    vero, solo un prefisso comune abbastanza lungo da non essere casuale.

    L'ultima lettera del confronto viene ignorata apposta: il singolare e il
    plurale italiani spesso differiscono solo nella vocale finale
    ("spesa"/"spese", "debito"/"debiti") — un bug reale trovato provando dal
    vivo su Trevalli (3 settembre 2026): "spesa"/"spese" sono entrambe di 5
    lettere, quindi il confronto a prefisso pieno (senza questo scarto)
    richiedeva tutte e 5 le lettere uguali e falliva proprio sull'ultima.

    Richiede anche lunghezze vicine (differenza massima 2): senza questo
    vincolo, allentare il confronto ha aperto un secondo bug reale, trovato
    subito dopo aver corretto il primo — "spese" (5 lettere) iniziava a
    combaciare anche con "spesometro" (10 lettere, un adempimento fiscale
    tutt'altra cosa) perché condividono le prime 4 lettere per puro caso. Un
    vero singolare/plurale italiano non si allunga così tanto."""
    if abs(len(a) - len(b)) > 2:
        return False
    n = min(len(a), len(b))
    if n < _LUNGHEZZA_MINIMA_TOKEN:
        return False
    n_confronto = max(n - 1, _LUNGHEZZA_MINIMA_TOKEN)
    return a[:n_confronto] == b[:n_confronto]


def _punteggio(token_domanda: list[str], token_candidato: list[str]) -> int:
    return sum(1 for td in token_domanda for tc in token_candidato if _radice_comune(td, tc))


def _migliore(domanda: str, candidati: list[tuple[str, list[str]]]) -> str | None:
    """`candidati`: coppie (identificativo, token) — ritorna l'identificativo
    col punteggio più alto, None se nessuno condivide almeno un token.

    Scorciatoia prima del confronto a token: se la domanda è (a meno di
    maiuscole/spazi) esattamente il nome di uno dei candidati, usa quello
    subito. Bug reale trovato provando dal vivo (3 settembre 2026): cercare
    letteralmente "CGDatiFatturaR" trovava "CGDatiFatturaE" — le due
    tabelle producono lo STESSO insieme di token (la lettera finale che le
    distingue, R vs E, è troppo corta per essere un token da sola) e a
    parità di punteggio vince solo chi viene prima nell'elenco, non chi
    corrisponde davvero al nome cercato."""
    domanda_pulita = domanda.strip().lower()
    for identificativo, _token_candidato in candidati:
        if identificativo.lower() == domanda_pulita:
            return identificativo

    token_domanda = _token(domanda)
    if not token_domanda:
        return None
    migliore_id: str | None = None
    migliore_punteggio = 0
    for identificativo, token in candidati:
        p = _punteggio(token_domanda, token)
        if p > migliore_punteggio:
            migliore_id, migliore_punteggio = identificativo, p
    return migliore_id


def trova_tabella_per_nome(connection_string: str, termine: str) -> str | None:
    """Wrapper pubblico: il nome della tabella più pertinente al termine tra
    TUTTE quelle del database (non solo quelle "interessanti" per un
    andamento) — usato da services.vista_automatica e
    services.segnalazione_automatica, che devono poter scegliere qualunque
    tabella, anche senza una colonna numerica plausibile."""
    engine = db_engine.get_engine(connection_string)
    nomi = db_engine.list_table_names(engine)
    return _migliore(termine, [(n, _token(n)) for n in nomi])


def tabelle_note(connection_string: str) -> list[dict[str, Any]]:
    """Le tabelle con un andamento riconosciuto (stesse di Andamenti) — usate
    sia per il matching di primo livello sia per elencarle onestamente
    all'utente quando non si trova nulla di pertinente."""
    return analisi_automatica.analizza_integrazione(connection_string)


def _conta_e_somma(connection_string: str, nome_tabella: str) -> dict[str, Any]:
    """Risposta "povera" (livello 2): conteggio righe sempre, più una somma
    se la tabella ha una colonna numerica plausibile (stessa euristica di
    Andamenti) — non un andamento nel tempo, solo un totale attuale."""
    engine = db_engine.get_engine(connection_string)
    insp = inspect(engine)
    colonne = insp.get_columns(nome_tabella)
    pk = set((insp.get_pk_constraint(nome_tabella) or {}).get("constrained_columns") or [])
    colonna_numero = analisi_automatica.colonna_numerica_plausibile(colonne, pk)

    with engine.connect() as conn:
        righe = conn.execute(text(f'SELECT COUNT(*) FROM "{nome_tabella}"')).scalar() or 0
        somma = None
        if colonna_numero:
            somma = conn.execute(text(f'SELECT SUM("{colonna_numero}") FROM "{nome_tabella}"')).scalar()

    return {
        "tabella": nome_tabella,
        "righe": righe,
        "colonna_numero": colonna_numero,
        "somma": float(somma) if somma is not None else None,
    }


def cerca(connection_string: str, domanda: str) -> dict[str, Any] | None:
    """Punto d'ingresso: prova prima tra le tabelle "interessanti" già trovate
    da Andamenti (risposta più ricca, un andamento pronto), poi tra TUTTE le
    tabelle del database (risposta più povera). None se nessuna tabella
    sembra pertinente — non inventa mai una tabella a caso."""
    interessanti = tabelle_note(connection_string)
    match = _migliore(domanda, [(r["tabella"], _token(r["tabella"])) for r in interessanti])
    if match:
        trovato = next(r for r in interessanti if r["tabella"] == match)
        return {"tipo": "andamento", **trovato}

    match = trova_tabella_per_nome(connection_string, domanda)
    if not match:
        return None
    return {"tipo": "conteggio", **_conta_e_somma(connection_string, match)}
