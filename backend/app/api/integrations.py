"""
CRUD dell'Hub Integrazioni: l'utente collega qui le proprie credenziali esterne
(Gmail, Stripe, database ERP, ...) che l'Agente AI userà per eseguire azioni reali.
Le credenziali sono cifrate a riposo (vedi app.core.security) e non vengono mai
restituite in chiaro dalle API: solo mascherate.
"""
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.deps import get_connection_string, require_admin
from app.core.security import decrypt_credentials, encrypt_credentials, mask_credentials
from app.database import TENANT_DATA_DIR, get_db
from app.models.integrations import Integration
from app.models.user import User
from app.services import analisi_automatica, db_templates
from app.services.integration_providers import get_provider_catalog, get_provider_kind

router = APIRouter(prefix="/integrations", tags=["integrations"])


class IntegrationCreate(BaseModel):
    name: str
    provider: str
    credentials: dict[str, str]


class IntegrationUpdate(BaseModel):
    name: str | None = None
    credentials: dict[str, str] | None = None
    status: str | None = None


class ProvisionRequest(BaseModel):
    name: str
    template: str = "blank"


class IntegrationResponse(BaseModel):
    id: int
    name: str
    provider: str
    kind: str
    status: str
    credentials_preview: dict[str, str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


def _to_response(integration: Integration) -> IntegrationResponse:
    preview = mask_credentials(decrypt_credentials(integration.credentials))
    return IntegrationResponse(
        id=integration.id,
        # Ripiego solo per le integrazioni create prima che il nome fosse
        # obbligatorio: non dovrebbe più comparire per quelle nuove.
        name=integration.name or f"{integration.provider} #{integration.id}",
        provider=integration.provider,
        kind=get_provider_kind(integration.provider),
        status=integration.status,
        credentials_preview=preview,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
    )


def _get_owned_integration(integration_id: int, current_user: User, db: Session) -> Integration:
    integration = db.get(Integration, integration_id)
    if integration is None or integration.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integrazione non trovata")
    return integration


@router.get("/providers")
def list_providers() -> list[dict]:
    """Catalogo dei provider noti (kind + campi credenziali attesi), per costruire il form."""
    return get_provider_catalog()


@router.get("/templates")
def list_templates() -> list[dict]:
    """Template disponibili per provisionare un database gestito da Cortex."""
    return db_templates.get_template_catalog()


@router.get("", response_model=list[IntegrationResponse])
def list_integrations(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[IntegrationResponse]:
    """Elenca le integrazioni collegate dall'azienda, con credenziali mascherate."""
    integrations = (
        db.query(Integration)
        .filter(Integration.organization_id == current_user.organization_id)
        .order_by(Integration.created_at)
        .all()
    )
    return [_to_response(i) for i in integrations]


@router.post("", response_model=IntegrationResponse, status_code=status.HTTP_201_CREATED)
def create_integration(
    payload: IntegrationCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> IntegrationResponse:
    """Salva una nuova integrazione, cifrando le credenziali prima di persisterle."""
    if not payload.name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Il nome è obbligatorio")
    if not payload.credentials:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Credenziali mancanti")

    integration = Integration(
        organization_id=current_user.organization_id,
        name=payload.name.strip(),
        provider=payload.provider,
        credentials=encrypt_credentials(payload.credentials),
        status="connected",
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)
    return _to_response(integration)


@router.post("/provision", response_model=IntegrationResponse, status_code=status.HTTP_201_CREATED)
def provision_managed_database(
    payload: ProvisionRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> IntegrationResponse:
    """Crea un database dedicato e isolato per il tenant, ospitato da Cortex,
    per chi non ha ancora un proprio database/ERP esterno da collegare. Stesso
    Data Explorer generico di un'integrazione 'database_external': cambia solo
    chi ospita i dati, non come vengono esplorati."""
    if not payload.name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Il nome è obbligatorio")
    if payload.template not in db_templates.TEMPLATES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Template non valido")

    TENANT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    db_path = TENANT_DATA_DIR / f"org{current_user.organization_id}_{uuid4().hex[:8]}.db"
    connection_string = db_templates.provision_database(db_path, payload.template)

    integration = Integration(
        organization_id=current_user.organization_id,
        name=payload.name.strip(),
        provider="cortex_managed_db",
        credentials=encrypt_credentials({"connection_string": connection_string, "template": payload.template}),
        status="connected",
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)
    return _to_response(integration)


@router.put("/{integration_id}", response_model=IntegrationResponse)
def update_integration(
    integration_id: int,
    payload: IntegrationUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> IntegrationResponse:
    """Aggiorna nome, credenziali e/o stato di un'integrazione esistente."""
    integration = _get_owned_integration(integration_id, current_user, db)

    if payload.name is not None:
        if not payload.name.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Il nome è obbligatorio")
        integration.name = payload.name.strip()
    if payload.credentials is not None:
        if not payload.credentials:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Credenziali mancanti")
        integration.credentials = encrypt_credentials(payload.credentials)
    if payload.status is not None:
        integration.status = payload.status

    db.commit()
    db.refresh(integration)
    return _to_response(integration)


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_integration(
    integration_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    """Scollega definitivamente un'integrazione."""
    integration = _get_owned_integration(integration_id, current_user, db)
    db.delete(integration)
    db.commit()


@router.get("/{integration_id}/analisi-automatica")
def get_analisi_automatica(connection_string: str = Depends(get_connection_string)) -> list[dict]:
    """Grafici che Cortex trova e disegna da solo, senza nessuna Vista o
    Segnalazione da configurare — vedi services/analisi_automatica.py.
    Funziona su qualunque database collegato, non solo Sampeyre/Arca: non
    richiede nessun profilo contabile riconosciuto. Ritorna direttamente
    nella forma già pronta per WidgetCanvas (stesso principio già usato per
    i "modelli pronti" di Arca in api/accounting.py), zero rendering nuovo
    lato frontend."""
    risultati = analisi_automatica.analizza_integrazione(connection_string)
    return [
        {
            "type": "line",
            "title": f"{r['tabella']} — andamento di {r['colonna_numero']}",
            "labels": [p["periodo"] for p in r["andamento"]],
            "series": [{"name": r["colonna_numero"], "data": [p["totale"] for p in r["andamento"]]}],
            "tabella": r["tabella"],
            "righe_totali": r["righe_totali"],
        }
        for r in risultati
    ]
