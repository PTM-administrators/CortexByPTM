"""
Fixture condivise dai test. Il database usato qui non è mai
`cortex_enterprise.db` (quello vero, con Sampeyre/Trevalli/tutti i dati
reali con cui lavoriamo nelle sessioni di sviluppo): ogni test riceve un
database SQLite in memoria, nuovo di zecca, con lo schema creato al volo da
`Base.metadata.create_all` — non serve passare da Alembic (più lento, e i
test non devono verificare le migrazioni, solo il comportamento
dell'applicazione). Sparisce da solo alla fine del test, nessun file da
ripulire.

`TestClient(app)` viene istanziato SENZA `with ... as client:` — questo
evita di far scattare il lifespan di FastAPI (vedi app/main.py), che
altrimenti avvierebbe lo scheduler in background (app.services.scheduler)
puntato sul database VERO: nei test quel loop non serve e non deve
esistere.
"""
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 — registra tutti i modelli su Base.metadata
from app.core.security import create_access_token, encrypt_credentials, hash_password
from app.database import Base, get_db
from app.main import app
from app.models.membership import RUOLO_ADMIN, RUOLO_READONLY, Membership
from app.models.organization import Organization
from app.models.user import User


@pytest.fixture()
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # una sola connessione condivisa: senza, ogni sessione vedrebbe un :memory: diverso
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def crea_organizzazione_con_admin(
    db: Session, company_name: str = "Azienda Test", industry: str = "generic"
) -> tuple[Organization, User]:
    """Un'azienda con un primo utente admin — la scorciatoia usata da quasi
    ogni test che non riguarda specificamente la registrazione in sé."""
    org = Organization(company_name=company_name, industry=industry)
    db.add(org)
    db.flush()
    user = User(email=f"admin{org.id}@test.example.com", hashed_password=hash_password("Password123!"), organization_id=org.id)
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role=RUOLO_ADMIN))
    db.commit()
    db.refresh(user)
    return org, user


def aggiungi_membro(db: Session, org: Organization, role: str = RUOLO_READONLY) -> User:
    """Un ulteriore utente della stessa azienda, con il ruolo indicato."""
    user = User(
        email=f"membro{org.id}-{role}-{db.query(User).count()}@test.example.com",
        hashed_password=hash_password("Password123!"),
        organization_id=org.id,
    )
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role=role))
    db.commit()
    db.refresh(user)
    return user


def token_di(user: User) -> str:
    return create_access_token({"sub": str(user.id)})


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_di(user)}"}


def crea_integrazione_db(db: Session, org: Organization, connection_string: str, name: str = "DB test", provider: str = "custom_db"):
    """Un'integrazione di tipo database, con connection string cifrata come
    farebbe l'app vera — serve ai test che passano da endpoint che
    decifrano davvero le credenziali (es. /agent/chat, /data)."""
    from app.models.integrations import Integration

    integration = Integration(
        organization_id=org.id,
        name=name,
        provider=provider,
        credentials=encrypt_credentials({"connection_string": connection_string}),
        status="connected",
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)
    return integration
