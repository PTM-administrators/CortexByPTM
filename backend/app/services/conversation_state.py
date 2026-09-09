"""
Memoria conversazionale della chat: le ultime battute di ogni utente, per
poter capire un riferimento come "e il mese scorso?" senza che l'utente
debba ripetere da capo modo/tipo/periodo — prima di questa modifica ogni
messaggio veniva deciso da solo, senza nessuna nozione di cosa fosse stato
chiesto prima (feedback dell'utente, 3 settembre 2026: "la chat al momento
è piuttosto inutile").

Stessa scelta implementativa di app.services.agent_state (dict di processo,
non una tabella): la cronologia serve solo a rendere fluida la sessione
attiva, non deve sopravvivere a un riavvio del server, e il volume di un
singolo utente non giustifica altro.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Ultimi 6 messaggi (3 scambi utente/agente): basta per un riferimento a
# "quello di prima", non un transcript enorme da rimandare ad ogni chiamata
# a un LLM vero (costa in token e in tempo, non solo in "richieste al giorno").
_MAX_TURNI = 6


@dataclass
class Turno:
    ruolo: str  # "utente" | "assistente"
    testo: str
    creato_il: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class _StatoUtente:
    turni: list[Turno] = field(default_factory=list)
    # Argomenti dell'ultima richiesta di visualizzazione risolta con successo
    # (modo/tipo/periodi...) — permette a StubLLMClient di "ereditare" cosa si
    # stava guardando quando il messaggio successivo è solo un riferimento
    # relativo ("e il mese scorso?"), senza dover ricapire tutto da zero.
    # Non impostato per email/ricerca/esplorazione libera: non ha senso
    # "ereditarle" allo stesso modo di un periodo contabile.
    ultimo_contesto_visualizzazione: dict[str, Any] | None = None


_STATI: dict[int, _StatoUtente] = {}


def _stato(user_id: int) -> _StatoUtente:
    return _STATI.setdefault(user_id, _StatoUtente())


def aggiungi_turno(user_id: int, ruolo: str, testo: str) -> None:
    if not testo:
        return  # una risposta vuota (es. bozza email ancora incompleta) non aggiunge contesto utile
    turni = _stato(user_id).turni
    turni.append(Turno(ruolo=ruolo, testo=testo))
    del turni[:-_MAX_TURNI]


def storico(user_id: int) -> list[Turno]:
    return list(_stato(user_id).turni)


def imposta_ultimo_contesto_visualizzazione(user_id: int, args: dict[str, Any]) -> None:
    _stato(user_id).ultimo_contesto_visualizzazione = dict(args)


def ultimo_contesto_visualizzazione(user_id: int) -> dict[str, Any] | None:
    contesto = _stato(user_id).ultimo_contesto_visualizzazione
    return dict(contesto) if contesto else None


def azzera(user_id: int) -> None:
    """Dimentica la conversazione di un utente. Non ancora richiamata da
    nessun endpoint (nessun bottone "nuova conversazione" nel frontend oggi)
    ma utile per i test e pronta se in futuro ne servirà uno."""
    _STATI.pop(user_id, None)
