"""
Autenticazione, appartenenza multi-azienda e ruoli (vedi
app/models/membership.py, introdotti il 3 settembre 2026). La parte più
delicata da proteggere con test automatici: un bug qui non è "un grafico
sbagliato", è "un utente sola lettura che riesce a scrivere" o "un utente
che vede i dati di un'altra azienda".
"""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.membership import Membership
from tests.conftest import aggiungi_membro, auth_headers, crea_organizzazione_con_admin


def _membership_id_di(db: Session, user_id: int) -> int:
    return db.query(Membership).filter(Membership.user_id == user_id).first().id


def test_registrazione_nuova_azienda_diventa_admin(client: TestClient) -> None:
    risposta = client.post(
        "/api/auth/register",
        json={"email": "nuovo@test.example.com", "password": "Password123!", "company_name": "Azienda Nuova"},
    )
    assert risposta.status_code == 201
    corpo = risposta.json()
    assert corpo["role"] == "admin"
    assert corpo["company_name"] == "Azienda Nuova"


def test_registrazione_con_invito_diventa_readonly(client: TestClient, db_session: Session) -> None:
    org, _admin = crea_organizzazione_con_admin(db_session)

    risposta = client.post(
        "/api/auth/register",
        json={"email": "dipendente@test.example.com", "password": "Password123!", "invite_code": org.invite_code},
    )
    assert risposta.status_code == 201
    corpo = risposta.json()
    assert corpo["role"] == "readonly", "chi si unisce con un codice invito deve partire in sola lettura"
    assert corpo["organization_id"] == org.id


def test_registrazione_email_duplicata_rifiutata(client: TestClient) -> None:
    payload = {"email": "duplicato@test.example.com", "password": "Password123!", "company_name": "A"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    seconda = client.post("/api/auth/register", json=payload)
    assert seconda.status_code == 400


def test_login_password_sbagliata_rifiutato(client: TestClient, db_session: Session) -> None:
    org, admin = crea_organizzazione_con_admin(db_session)
    risposta = client.post(
        "/api/auth/login", data={"username": admin.email, "password": "password-sbagliata"}
    )
    assert risposta.status_code == 401


def test_me_ritorna_il_ruolo_nellazienda_attiva(client: TestClient, db_session: Session) -> None:
    org, admin = crea_organizzazione_con_admin(db_session)
    risposta = client.get("/api/auth/me", headers=auth_headers(admin))
    assert risposta.status_code == 200
    assert risposta.json()["role"] == "admin"


def test_switch_organization_rifiuta_senza_membership(client: TestClient, db_session: Session) -> None:
    _org1, admin1 = crea_organizzazione_con_admin(db_session, "Azienda Uno")
    org2, _admin2 = crea_organizzazione_con_admin(db_session, "Azienda Due")

    risposta = client.post(
        "/api/auth/switch-organization", json={"organization_id": org2.id}, headers=auth_headers(admin1)
    )
    assert risposta.status_code == 403


class TestRequireAdmin:
    """Ogni endpoint che modifica qualcosa di persistente o invia qualcosa
    verso l'esterno deve rifiutare un utente "readonly" con 403, e accettare
    un "admin" — vedi api/deps.require_admin, applicato endpoint per
    endpoint. Un solo test per famiglia di endpoint, non ogni possibile
    payload: qui l'obiettivo è "il cancello è chiuso", non "la logica
    dietro il cancello è corretta" (quella la testano gli altri file)."""

    def test_readonly_non_puo_creare_integrazione(self, client: TestClient, db_session: Session) -> None:
        org, _admin = crea_organizzazione_con_admin(db_session)
        readonly = aggiungi_membro(db_session, org, "readonly")

        risposta = client.post(
            "/api/integrations",
            json={"name": "Prova", "provider": "gmail", "credentials": {"a": "b"}},
            headers=auth_headers(readonly),
        )
        assert risposta.status_code == 403

    def test_admin_puo_creare_integrazione(self, client: TestClient, db_session: Session) -> None:
        org, admin = crea_organizzazione_con_admin(db_session)
        risposta = client.post(
            "/api/integrations",
            json={"name": "Prova", "provider": "gmail", "credentials": {"a": "b"}},
            headers=auth_headers(admin),
        )
        assert risposta.status_code == 201

    def test_readonly_puo_leggere_integrazioni(self, client: TestClient, db_session: Session) -> None:
        org, _admin = crea_organizzazione_con_admin(db_session)
        readonly = aggiungi_membro(db_session, org, "readonly")
        risposta = client.get("/api/integrations", headers=auth_headers(readonly))
        assert risposta.status_code == 200

    def test_readonly_non_puo_creare_vista(self, client: TestClient, db_session: Session) -> None:
        org, admin = crea_organizzazione_con_admin(db_session)
        readonly = aggiungi_membro(db_session, org, "readonly")
        integrazione = client.post(
            "/api/integrations",
            json={"name": "DB", "provider": "custom_db", "credentials": {"connection_string": "sqlite:///:memory:"}},
            headers=auth_headers(admin),
        ).json()

        risposta = client.post(
            "/api/views",
            json={
                "integration_id": integrazione["id"],
                "table_name": "qualunque",
                "name": "Vista prova",
                "mode": "table",
            },
            headers=auth_headers(readonly),
        )
        assert risposta.status_code == 403

    def test_readonly_non_puo_regenerare_invito(self, client: TestClient, db_session: Session) -> None:
        org, _admin = crea_organizzazione_con_admin(db_session)
        readonly = aggiungi_membro(db_session, org, "readonly")
        risposta = client.post("/api/team/invite/regenerate", headers=auth_headers(readonly))
        assert risposta.status_code == 403


class TestGestioneRuoli:
    def test_admin_puo_promuovere_un_membro(self, client: TestClient, db_session: Session) -> None:
        org, admin = crea_organizzazione_con_admin(db_session)
        readonly = aggiungi_membro(db_session, org, "readonly")
        membership_id = _membership_id_di(db_session, readonly.id)

        risposta = client.post(
            f"/api/team/members/{membership_id}/role", json={"role": "admin"}, headers=auth_headers(admin)
        )
        assert risposta.status_code == 200
        membri = {m["user_id"]: m["role"] for m in risposta.json()["members"]}
        assert membri[readonly.id] == "admin"

    def test_readonly_non_puo_cambiare_ruoli(self, client: TestClient, db_session: Session) -> None:
        org, admin = crea_organizzazione_con_admin(db_session)
        readonly = aggiungi_membro(db_session, org, "readonly")
        admin_membership_id = _membership_id_di(db_session, admin.id)
        risposta = client.post(
            f"/api/team/members/{admin_membership_id}/role", json={"role": "readonly"}, headers=auth_headers(readonly)
        )
        assert risposta.status_code == 403

    def test_non_si_puo_retrocedere_lultimo_admin(self, client: TestClient, db_session: Session) -> None:
        org, admin = crea_organizzazione_con_admin(db_session)  # unico membro, unico admin
        admin_membership_id = _membership_id_di(db_session, admin.id)
        risposta = client.post(
            f"/api/team/members/{admin_membership_id}/role", json={"role": "readonly"}, headers=auth_headers(admin)
        )
        assert risposta.status_code == 400

    def test_si_puo_retrocedere_un_admin_se_ce_ne_un_altro(self, client: TestClient, db_session: Session) -> None:
        org, admin = crea_organizzazione_con_admin(db_session)
        secondo_admin = aggiungi_membro(db_session, org, "admin")
        secondo_membership_id = _membership_id_di(db_session, secondo_admin.id)
        risposta = client.post(
            f"/api/team/members/{secondo_membership_id}/role",
            json={"role": "readonly"},
            headers=auth_headers(admin),
        )
        assert risposta.status_code == 200

    def test_team_mostra_tutti_i_membri_non_solo_chi_ha_questa_azienda_attiva(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Regressione: prima del 3 settembre 2026 la pagina Team leggeva
        User.organization_id (l'azienda ATTIVA in questo momento) invece
        della vera appartenenza (Membership) — un membro che stava
        guardando un'altra delle sue aziende spariva dall'elenco."""
        org, admin = crea_organizzazione_con_admin(db_session)
        secondo = aggiungi_membro(db_session, org, "readonly")
        altra_org, _altro_admin = crea_organizzazione_con_admin(db_session, "Altra Azienda")
        secondo.organization_id = altra_org.id  # "sta guardando" un'altra azienda in questo momento
        db_session.commit()

        risposta = client.get("/api/team", headers=auth_headers(admin))
        assert risposta.status_code == 200
        email_membri = {m["email"] for m in risposta.json()["members"]}
        assert secondo.email in email_membri
