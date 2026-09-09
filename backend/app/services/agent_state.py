"""
Azioni "pendenti" dell'agente: quando l'agente decide un'azione con effetti
verso l'esterno (oggi: inviare un'email), non la esegue subito — la mette qui
in attesa di conferma esplicita dall'utente (POST /api/agent/confirm/{id}).

Implementazione in memoria (un dict di processo): le azioni pendenti non
sopravvivono a un riavvio del server. Accettabile per un flusso "conferma
quasi subito, stesso processo"; da spostare su una tabella se in futuro serve
persistenza più lunga (es. conferme via email asincrone).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class PendingAction:
    id: str
    user_id: int
    tool: str
    arguments: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_PENDING: dict[str, PendingAction] = {}


def create_pending_action(user_id: int, tool: str, arguments: dict[str, Any]) -> PendingAction:
    action = PendingAction(id=str(uuid4()), user_id=user_id, tool=tool, arguments=arguments)
    _PENDING[action.id] = action
    return action


def pop_pending_action(action_id: str, user_id: int) -> PendingAction | None:
    """Rimuove e ritorna l'azione pendente se esiste ed è dell'utente giusto —
    'pop', non 'get': un'azione confermata si esegue una volta sola."""
    action = _PENDING.get(action_id)
    if action is None or action.user_id != user_id:
        return None
    del _PENDING[action_id]
    return action
