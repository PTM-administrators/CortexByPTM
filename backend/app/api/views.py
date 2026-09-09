"""
Viste salvate: configurare una volta come vedere una tabella o risorsa API
collegata (a schede, a calendario, o a tabella con azioni per riga) e
riusarla — senza scrivere codice per ogni nuovo settore. Generalizza il
"visualize_tool" della finanza no-profit (che conosce solo il proprio schema)
a qualunque azienda: un immobiliare vede i suoi annunci a schede (dal proprio
database o dall'API di un portale, vedi app.services.data_source), un
barbiere i suoi appuntamenti a calendario, un'azienda qualunque aggiunge un
bottone "Sollecito" su una tabella di debitori.

Le azioni per riga (oggi: invio email) riusano lo stesso meccanismo di
conferma già collaudato per la chat: si crea un'azione "pendente"
(app.services.agent_state) ed è POST /api/agent/confirm/{id} — lo stesso
endpoint, non uno nuovo — che la esegue davvero dopo la conferma dell'utente.
"""
import json
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.deps import require_admin
from app.database import get_db
from app.models.integrations import Integration
from app.models.saved_view import SavedView
from app.models.user import User
from app.services import agent_state, data_source, export_engine, view_rendering
from app.services.templating import applica_template

_LIMITE_EXPORT = 20_000  # stesso limite generoso di api/data_explorer.py

router = APIRouter(prefix="/views", tags=["views"])

_MODI_VALIDI = view_rendering._MODI_VALIDI


class ViewCreate(BaseModel):
    integration_id: int
    table_name: str
    name: str
    mode: str
    column_mapping: dict[str, str] = {}
    row_actions: list[dict[str, str]] = []


class ViewResponse(BaseModel):
    id: int
    integration_id: int
    table_name: str
    name: str
    mode: str
    column_mapping: dict[str, str]
    row_actions: list[dict[str, str]]


class PendingActionResponse(BaseModel):
    id: str
    tool: str
    preview: dict[str, Any]


def _to_response(view: SavedView) -> ViewResponse:
    return ViewResponse(
        id=view.id,
        integration_id=view.integration_id,
        table_name=view.table_name,
        name=view.name,
        mode=view.mode,
        column_mapping=json.loads(view.column_mapping),
        row_actions=json.loads(view.row_actions),
    )


def _get_owned_view(view_id: int, current_user: User, db: Session) -> SavedView:
    view = db.get(SavedView, view_id)
    if view is None or view.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vista non trovata")
    return view


def _data_source_for(view: SavedView, current_user: User, db: Session) -> data_source.DataSource:
    integration = db.get(Integration, view.integration_id)
    if integration is None or integration.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integrazione della vista non trovata")
    try:
        return data_source.resolve(integration)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("", response_model=ViewResponse, status_code=status.HTTP_201_CREATED)
def create_view(
    payload: ViewCreate, current_user: User = Depends(require_admin), db: Session = Depends(get_db)
) -> ViewResponse:
    if payload.mode not in _MODI_VALIDI:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"mode deve essere uno tra {_MODI_VALIDI}")

    integration = db.get(Integration, payload.integration_id)
    if integration is None or integration.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integrazione non trovata")

    view = SavedView(
        organization_id=current_user.organization_id,
        integration_id=payload.integration_id,
        table_name=payload.table_name,
        name=payload.name,
        mode=payload.mode,
        column_mapping=json.dumps(payload.column_mapping),
        row_actions=json.dumps(payload.row_actions),
    )
    db.add(view)
    db.commit()
    db.refresh(view)
    return _to_response(view)


@router.get("", response_model=list[ViewResponse])
def list_views(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ViewResponse]:
    views = (
        db.query(SavedView)
        .filter(SavedView.organization_id == current_user.organization_id)
        .order_by(SavedView.created_at)
        .all()
    )
    return [_to_response(v) for v in views]


@router.delete("/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_view(view_id: int, current_user: User = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    view = _get_owned_view(view_id, current_user, db)
    db.delete(view)
    db.commit()


@router.get("/{view_id}/data")
def get_view_data(view_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Righe correnti della tabella collegata, formattate secondo la modalità
    della vista — pronte per WidgetCanvas, senza che il frontend debba sapere
    nulla dello schema originale."""
    view = _get_owned_view(view_id, current_user, db)
    source = _data_source_for(view, current_user, db)

    try:
        return view_rendering.render_view_data(view, source)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Impossibile leggere la tabella collegata: {exc}"
        ) from exc


@router.get("/{view_id}/export.xlsx")
def export_view_excel(
    view_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    """Le righe grezze della tabella collegata alla vista, in Excel — non la
    resa a schede/calendario (quella è per leggere a schermo), i dati così
    come sono nella sorgente. Comodo per chi è già su questa vista e non
    vuole andare a cercarla in Integrazioni/Dati."""
    view = _get_owned_view(view_id, current_user, db)
    source = _data_source_for(view, current_user, db)
    try:
        risultato = data_source.list_rows(source, view.table_name, limit=_LIMITE_EXPORT, offset=0)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Impossibile leggere la tabella collegata: {exc}"
        ) from exc
    contenuto = export_engine.righe_a_excel(risultato["columns"], risultato["rows"], titolo=view.name)
    nome_file = quote(f"{view.name}.xlsx")
    return Response(
        content=contenuto,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{nome_file}"},
    )


@router.post("/{view_id}/rows/{pk_value}/actions/{action_index}", response_model=PendingActionResponse)
def trigger_row_action(
    view_id: int,
    pk_value: str,
    action_index: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PendingActionResponse:
    """Prepara (non esegue) l'azione di riga: costruisce oggetto/corpo
    dell'email dai valori reali della riga e crea un'azione pendente — la
    stessa in attesa di conferma della chat (POST /api/agent/confirm/{id})."""
    view = _get_owned_view(view_id, current_user, db)
    if view.mode != "table":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le azioni esistono solo per le viste a tabella")

    row_actions = json.loads(view.row_actions)
    if not (0 <= action_index < len(row_actions)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Azione non trovata")
    azione = row_actions[action_index]

    source = _data_source_for(view, current_user, db)
    try:
        riga = data_source.get_row(source, view.table_name, pk_value)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Impossibile leggere la riga: {exc}") from exc
    if riga is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Riga non trovata")

    to_address = riga.get(azione.get("to_colonna", ""))
    if not to_address:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La riga non ha un indirizzo email valido nella colonna '{azione.get('to_colonna')}'",
        )

    arguments = {
        "to_address": to_address,
        "subject": applica_template(azione.get("oggetto_template", ""), riga),
        "body": applica_template(azione.get("corpo_template", ""), riga),
    }
    action = agent_state.create_pending_action(current_user.id, "email_tool", arguments)
    return PendingActionResponse(id=action.id, tool="email_tool", preview=arguments)


@router.get("/{view_id}/rows/{pk_value}")
def get_view_row(
    view_id: int,
    pk_value: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Dettaglio completo di una singola riga — usato per "espandere" una
    scheda (modalità cards) e mostrare tutte le informazioni disponibili, non
    solo titolo/sottotitolo/badge. Per una vista su database è la stessa riga
    già vista nell'elenco (una riga SQL non ha altro da mostrare); per una
    vista su API REST può essere molto di più, se l'integrazione ha un
    endpoint di dettaglio configurato (vedi app.services.api_connector)."""
    view = _get_owned_view(view_id, current_user, db)
    source = _data_source_for(view, current_user, db)
    try:
        riga = data_source.get_row(source, view.table_name, pk_value)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Impossibile leggere la riga: {exc}") from exc
    if riga is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Riga non trovata")
    return riga
