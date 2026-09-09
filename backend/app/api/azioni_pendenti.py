"""
Azioni pronte preparate da Cortex da solo (vedi models.AzionePendente,
services/notifiche.py._prepara_azione_se_configurata) — tipicamente un
sollecito già scritto per un debitore/fornitore scaduto, in attesa che un
amministratore lo confermi con un click o lo rifiuti. L'invio vero passa
sempre da qui (mai automatico): stessa regola di sicurezza già applicata
alle email preparate dall'agente in chat (api/agent.py).
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.deps import require_admin
from app.core.security import decrypt_credentials
from app.database import get_db
from app.models.azione_pendente import AzionePendente
from app.models.integrations import Integration
from app.models.user import User
from app.tools import email_tool

router = APIRouter(prefix="/azioni-pendenti", tags=["azioni-pendenti"])


class AzionePendenteResponse(BaseModel):
    id: int
    origine: str
    to_address: str
    subject: str
    body: str
    stato: str
    created_at: datetime

    model_config = {"from_attributes": True}


def _get_owned_azione(azione_id: int, current_user: User, db: Session) -> AzionePendente:
    azione = db.get(AzionePendente, azione_id)
    if azione is None or azione.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Azione non trovata")
    return azione


@router.get("", response_model=list[AzionePendenteResponse])
def list_azioni_pendenti(
    solo_in_attesa: bool = True, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[AzionePendente]:
    query = db.query(AzionePendente).filter(AzionePendente.organization_id == current_user.organization_id)
    if solo_in_attesa:
        query = query.filter(AzionePendente.stato == "in_attesa")
    return query.order_by(AzionePendente.created_at.desc()).all()


@router.post("/{azione_id}/conferma", response_model=AzionePendenteResponse)
def conferma_azione(
    azione_id: int, current_user: User = Depends(require_admin), db: Session = Depends(get_db)
) -> AzionePendente:
    """Invia davvero l'azione preparata, tramite l'integrazione Gmail/SMTP
    già collegata dall'azienda — stessa integrazione usata per ogni altro
    invio email di Cortex, nessuna configurazione diversa."""
    azione = _get_owned_azione(azione_id, current_user, db)
    if azione.stato != "in_attesa":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Questa azione non è più in attesa")

    integrazione = (
        db.query(Integration)
        .filter(Integration.organization_id == current_user.organization_id, Integration.provider == "gmail")
        .order_by(Integration.created_at)
        .first()
    )
    if integrazione is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Integrazione Gmail/SMTP non collegata: configurala nella pagina Integrazioni.",
        )

    credenziali = decrypt_credentials(integrazione.credentials)
    try:
        email_tool.send_email(
            smtp_host=credenziali.get("smtp_host", ""),
            smtp_port=int(credenziali.get("smtp_port", 587) or 587),
            username=credenziali.get("username", ""),
            password=credenziali.get("password", ""),
            to_address=azione.to_address,
            subject=azione.subject,
            body=azione.body,
        )
    except Exception as exc:  # errori SMTP reali (auth, connessione, ecc.)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Invio non riuscito: {exc}") from exc

    azione.stato = "inviata"
    db.commit()
    db.refresh(azione)
    return azione


@router.post("/{azione_id}/rifiuta", response_model=AzionePendenteResponse)
def rifiuta_azione(
    azione_id: int, current_user: User = Depends(require_admin), db: Session = Depends(get_db)
) -> AzionePendente:
    """Scarta la bozza senza inviarla — non ritenta più, la stessa
    segnalazione non genererà una nuova bozza identica (vedi
    NotificaInviata: la chiave 'azione:...' resta segnata anche qui)."""
    azione = _get_owned_azione(azione_id, current_user, db)
    if azione.stato != "in_attesa":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Questa azione non è più in attesa")
    azione.stato = "rifiutata"
    db.commit()
    db.refresh(azione)
    return azione
