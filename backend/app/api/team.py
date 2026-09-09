"""
Gestione del team: membri della propria azienda (con il loro ruolo) e codice
invito per aggiungerne altri (vedi models/organization.py, api/auth.py). Non
esiste un limite al numero di amministratori — decisione confermata nel piano
di progetto — ma da quando esistono i ruoli (3 settembre 2026, vedi
models/membership.py) chi si unisce con il codice invito parte come sola
lettura, ed è un amministratore esistente a doverlo promuovere se serve.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.deps import require_admin
from app.database import get_db
from app.models.membership import RUOLO_ADMIN, RUOLO_READONLY, Membership
from app.models.organization import Organization, genera_invite_code
from app.models.user import User

router = APIRouter(prefix="/team", tags=["team"])

_RUOLI_VALIDI = (RUOLO_ADMIN, RUOLO_READONLY)


class MemberResponse(BaseModel):
    id: int  # id della Membership, non dell'utente: serve per POST /members/{id}/role
    user_id: int
    email: EmailStr
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TeamResponse(BaseModel):
    company_name: str
    invite_code: str
    members: list[MemberResponse]
    ruolo_attivo: str  # il ruolo di CHI STA GUARDANDO — il frontend lo usa per mostrare/nascondere i controlli di gestione


class RoleUpdateRequest(BaseModel):
    role: str


def _team_response(current_user: User, db: Session) -> TeamResponse:
    # Via Membership, non più via User.organization_id: quel campo è
    # l'azienda ATTIVA di un utente in questo momento, non l'elenco di chi ha
    # accesso — un membro che sta guardando un'altra delle sue aziende in
    # questo istante spariva dall'elenco pur avendo ancora accesso (bug
    # segnalato più volte, corretto qui insieme ai ruoli perché la stessa
    # riscrittura serviva comunque per mostrare il ruolo di ciascuno).
    righe = (
        db.query(Membership, User)
        .join(User, User.id == Membership.user_id)
        .filter(Membership.organization_id == current_user.organization_id)
        .order_by(Membership.created_at)
        .all()
    )
    membri = [
        MemberResponse(id=m.id, user_id=u.id, email=u.email, role=m.role, created_at=m.created_at)
        for m, u in righe
    ]
    mia_membership = next((m for m, _u in righe if m.user_id == current_user.id), None)
    return TeamResponse(
        company_name=current_user.organization.company_name,
        invite_code=current_user.organization.invite_code,
        members=membri,
        ruolo_attivo=mia_membership.role if mia_membership else RUOLO_READONLY,
    )


@router.get("", response_model=TeamResponse)
def get_team(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TeamResponse:
    """Membri della propria azienda (con ruolo) + codice invito per
    aggiungerne altri. Aperta a tutti, non solo agli admin: sapere chi c'è
    nel team è consultazione, non modifica."""
    return _team_response(current_user, db)


@router.post("/invite/regenerate", response_model=TeamResponse)
def regenerate_invite_code(current_user: User = Depends(require_admin), db: Session = Depends(get_db)) -> TeamResponse:
    """Genera un nuovo codice invito (il precedente smette di funzionare) —
    utile se il vecchio codice è stato condiviso per errore."""
    organization = db.get(Organization, current_user.organization_id)
    organization.invite_code = genera_invite_code()
    db.commit()
    db.refresh(organization)
    return _team_response(current_user, db)


@router.post("/members/{membership_id}/role", response_model=TeamResponse)
def update_member_role(
    membership_id: int,
    payload: RoleUpdateRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TeamResponse:
    """Promuove o retrocede un membro dell'azienda attiva. Due protezioni:
    non si può agire su una Membership di un'altra azienda (indovinando
    l'id), e non si può retrocedere l'ULTIMO admin rimasto — altrimenti
    l'azienda resterebbe senza nessuno che possa più gestirla (nemmeno per
    tornare admin da solo: nessun altro potrebbe promuoverlo)."""
    if payload.role not in _RUOLI_VALIDI:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"role deve essere uno tra {_RUOLI_VALIDI}")

    membership = db.get(Membership, membership_id)
    if membership is None or membership.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membro non trovato")

    if membership.role == RUOLO_ADMIN and payload.role != RUOLO_ADMIN:
        altri_admin = (
            db.query(Membership)
            .filter(
                Membership.organization_id == current_user.organization_id,
                Membership.role == RUOLO_ADMIN,
                Membership.id != membership.id,
            )
            .count()
        )
        if altri_admin == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Non puoi retrocedere l'ultimo amministratore rimasto: promuovi prima qualcun altro.",
            )

    membership.role = payload.role
    db.commit()
    return _team_response(current_user, db)
