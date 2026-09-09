"""
Endpoint della chat operativa e delle conferme: il punto di contatto tra il
Frontend e l'Agent Brain. /chat fa decidere ed eventualmente eseguire subito
un'azione di sola lettura; le azioni con effetti verso l'esterno (invio email)
restano "pendenti" finché non arrivano a /confirm/{action_id}.
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.deps import require_admin
from app.core.security import decrypt_credentials
from app.database import get_db
from app.models.integrations import Integration
from app.models.user import User
from app.services import agent_state
from app.services.agent_brain import AgentBrain
from app.tools import email_tool

router = APIRouter(prefix="/agent", tags=["agent"])


class ChatRequest(BaseModel):
    message: str


class PendingActionResponse(BaseModel):
    id: str
    tool: str
    preview: dict[str, Any]


class ChatResponse(BaseModel):
    action: str
    reply: str
    pending_action: PendingActionResponse | None = None
    # Forma generica, dispatchata dal frontend su "type": "bar"/"grouped_bar"/
    # "stacked_bar"/"line" (labels+series), "table" (columns+rows) o "cards"
    # (items) — vedi agent_brain.py._handle_visualize e WidgetCanvas.jsx.
    # Nessun modello Pydantic dedicato: la forma dipende dal type.
    widget: dict[str, Any] | None = None


class ConfirmResponse(BaseModel):
    status: str
    detail: dict[str, Any] | None = None


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatResponse:
    """Riceve un messaggio, fa decidere all'agente cosa fare ed esegue subito
    le azioni di sola lettura. Le azioni con effetti verso l'esterno tornano
    come `pending_action`, da confermare esplicitamente con /confirm."""
    brain = AgentBrain(db=db, current_user=current_user)
    result = brain.handle_message(payload.message)
    return ChatResponse(**result)


@router.post("/confirm/{action_id}", response_model=ConfirmResponse)
def confirm_action(
    action_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ConfirmResponse:
    """Esegue davvero un'azione pendente confermata dall'utente (oggi: invio
    email). L'azione viene rimossa dopo l'esecuzione: si può confermare una
    sola volta. Solo admin: preparare una bozza (POST /chat) resta aperto a
    tutti, inviarla davvero no (vedi models/membership.py)."""
    action = agent_state.pop_pending_action(action_id, current_user.id)
    if action is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Azione non trovata, già eseguita o scaduta.",
        )

    if action.tool != "email_tool":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Tool '{action.tool}' non eseguibile.")

    integration = (
        db.query(Integration)
        .filter(Integration.organization_id == current_user.organization_id, Integration.provider == "gmail")
        .order_by(Integration.created_at)
        .first()
    )
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Integrazione Gmail/SMTP non più disponibile: configurala nella pagina Integrazioni.",
        )

    credentials = decrypt_credentials(integration.credentials)
    try:
        risultato = email_tool.send_email(
            smtp_host=credentials.get("smtp_host", ""),
            smtp_port=int(credentials.get("smtp_port", 587) or 587),
            username=credentials.get("username", ""),
            password=credentials.get("password", ""),
            to_address=action.arguments["to_address"],
            subject=action.arguments.get("subject") or "Messaggio da Cortex",
            body=action.arguments.get("body", ""),
        )
    except Exception as exc:  # errori SMTP reali (auth, connessione, ecc.)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Invio non riuscito: {exc}"
        ) from exc

    return ConfirmResponse(status="eseguita", detail=risultato)
