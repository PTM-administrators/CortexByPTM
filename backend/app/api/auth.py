"""
Login, Registrazione, JWT Token.

La registrazione ha due modalità (vedi RegisterRequest): creare una nuova
azienda (organization) oppure unirsi a una esistente con un codice invito,
diventando un ulteriore amministratore con accesso agli stessi dati — non un
account separato con dati vuoti (vedi models/organization.py).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, model_validator
from sqlalchemy.orm import Session

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.database import get_db
from app.models.membership import RUOLO_ADMIN, RUOLO_READONLY, Membership, ruolo_attivo
from app.models.organization import Organization
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    # Modalità "nuova azienda": richiede company_name.
    company_name: str | None = None
    industry: str = "generic"
    # Modalità "unisciti a un'azienda esistente": in alternativa a company_name.
    invite_code: str | None = None

    @model_validator(mode="after")
    def _un_solo_modo(self) -> "RegisterRequest":
        if not self.invite_code and not self.company_name:
            raise ValueError("Serve 'company_name' (nuova azienda) oppure 'invite_code' (unisciti a una esistente)")
        return self


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    company_name: str
    industry: str
    # Id dell'azienda attiva — non solo il nome, così il frontend può
    # confrontarlo in modo affidabile con l'elenco di /auth/my-organizations
    # (due aziende potrebbero avere lo stesso nome, l'id no).
    organization_id: int
    # Ruolo dell'utente NELL'AZIENDA ATTIVA (vedi models/membership.py) — non
    # deducibile da User via from_attributes (vive sulla Membership, non su
    # User), va calcolato esplicitamente (vedi _user_response). Il frontend
    # lo usa per mostrare/nascondere i controlli che richiedono un admin,
    # senza dover tentare un'azione e scoprire il 403 dopo.
    role: str

    model_config = {"from_attributes": True}


def _user_response(db: Session, user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        company_name=user.company_name,
        industry=user.industry,
        organization_id=user.organization_id,
        role=ruolo_attivo(db, user),
    )


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Dependency FastAPI: risolve l'utente autenticato a partire dal JWT Token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenziali non valide",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None or "sub" not in payload:
        raise credentials_exception

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise credentials_exception
    return user


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> UserResponse:
    """Crea un nuovo utente: come amministratore di un'azienda nuova
    (company_name) oppure come membro di un'azienda già esistente
    (invite_code) — in questo secondo caso parte come "sola lettura"
    (vedi models/membership.py): il codice invito è pensato per un
    dipendente che deve consultare, non per un altro amministratore alla
    pari. Un admin esistente lo promuove dalla pagina Team se serve
    (POST /team/members/{id}/role) — diverso da join_organization, dove
    chi si aggiunge è già un utente Cortex esistente (tipicamente un
    consulente che segue più aziende clienti, vedi Portfolio) e resta admin."""
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email già registrata")

    if payload.invite_code:
        organization = db.query(Organization).filter(Organization.invite_code == payload.invite_code).first()
        if organization is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Codice invito non valido")
        ruolo = RUOLO_READONLY
    else:
        organization = Organization(company_name=payload.company_name, industry=payload.industry)
        db.add(organization)
        db.flush()  # serve l'id dell'organizzazione prima di creare l'utente
        ruolo = RUOLO_ADMIN

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        organization_id=organization.id,
    )
    db.add(user)
    db.flush()  # serve l'id dell'utente prima di creare la Membership
    db.add(Membership(user_id=user.id, organization_id=organization.id, role=ruolo))
    db.commit()
    db.refresh(user)
    return _user_response(db, user)


@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> TokenResponse:
    """Autentica l'utente (username=email) e ritorna un JWT Token."""
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o password non corrette",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def read_current_user(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserResponse:
    """Ritorna i dati dell'utente attualmente autenticato."""
    return _user_response(db, current_user)


# --- Più aziende per lo stesso utente --------------------------------------
#
# Chi usa Cortex per seguire più aziende clienti (alcune con un gestionale
# vero come Arca, altre senza nulla) non deve fare un login separato per
# ognuna: un utente può avere una Membership per ogni azienda a cui ha
# accesso, e "quella attiva" (User.organization_id, lo stesso campo che
# tutto il resto del backend legge già) si cambia con /switch-organization
# senza toccare il token — il JWT codifica solo l'utente, mai l'azienda.


class OrganizationSummary(BaseModel):
    id: int
    company_name: str
    industry: str

    model_config = {"from_attributes": True}


class SwitchOrganizationRequest(BaseModel):
    organization_id: int


class JoinOrganizationRequest(BaseModel):
    invite_code: str


class CreateOrganizationRequest(BaseModel):
    company_name: str
    industry: str = "generic"


def _le_mie_aziende(db: Session, user_id: int) -> list[Organization]:
    return (
        db.query(Organization)
        .join(Membership, Membership.organization_id == Organization.id)
        .filter(Membership.user_id == user_id)
        .order_by(Organization.company_name)
        .all()
    )


@router.get("/my-organizations", response_model=list[OrganizationSummary])
def get_my_organizations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Organization]:
    """Tutte le aziende a cui questo utente ha accesso (non solo quella
    attiva) — usata dal selettore azienda in Topbar.jsx e dal Portfolio."""
    return _le_mie_aziende(db, current_user.id)


@router.post("/switch-organization", response_model=UserResponse)
def switch_organization(
    payload: SwitchOrganizationRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> UserResponse:
    """Cambia l'azienda attiva tra quelle a cui l'utente ha già accesso —
    non un login diverso, lo stesso utente guarda dati diversi. Rifiutato
    se l'utente non ha una Membership per l'azienda richiesta: cambiare
    azienda non deve essere un modo per intrufolarsi in dati altrui
    indovinando un id."""
    membership = (
        db.query(Membership)
        .filter(Membership.user_id == current_user.id, Membership.organization_id == payload.organization_id)
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Non hai accesso a questa azienda")
    current_user.organization_id = payload.organization_id
    db.commit()
    db.refresh(current_user)
    return _user_response(db, current_user)


@router.post("/join-organization", response_model=UserResponse)
def join_organization(
    payload: JoinOrganizationRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> UserResponse:
    """Aggiunge un'azienda esistente all'elenco di quelle accessibili
    all'utente già loggato, tramite lo stesso codice invito usato in fase di
    registrazione (api/team.py) — e la rende subito l'azienda attiva. Un
    utente che ha già una Membership per quell'azienda la riusa senza
    duplicati (vincolo di unicità sulla tabella). A differenza di register()
    con invite_code, qui chi si aggiunge resta admin: questo endpoint è per
    un utente Cortex già esistente che comincia a seguire un'altra azienda
    cliente (il caso "consulente con più clienti", vedi Portfolio), non per
    un nuovo dipendente che si iscrive per la prima volta."""
    organization = db.query(Organization).filter(Organization.invite_code == payload.invite_code).first()
    if organization is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Codice invito non valido")

    esistente = (
        db.query(Membership)
        .filter(Membership.user_id == current_user.id, Membership.organization_id == organization.id)
        .first()
    )
    if esistente is None:
        db.add(Membership(user_id=current_user.id, organization_id=organization.id, role=RUOLO_ADMIN))

    current_user.organization_id = organization.id
    db.commit()
    db.refresh(current_user)
    return _user_response(db, current_user)


@router.post("/create-organization", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: CreateOrganizationRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> UserResponse:
    """Crea una nuova azienda (nuovo cliente) restando collegati con lo
    stesso account, invece di dover registrare un nuovo utente per ogni
    cliente — il caso comune di chi imposta Cortex per più aziende diverse.
    La rende subito l'azienda attiva. Sempre admin: chi la crea è per
    definizione il primo membro."""
    organization = Organization(company_name=payload.company_name, industry=payload.industry)
    db.add(organization)
    db.flush()
    db.add(Membership(user_id=current_user.id, organization_id=organization.id, role=RUOLO_ADMIN))
    current_user.organization_id = organization.id
    db.commit()
    db.refresh(current_user)
    return _user_response(db, current_user)
