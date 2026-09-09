"""
Segnalazioni proattive: regole configurabili una volta (vedi
app.services.alert_engine) che l'agente valuta da solo sui dati collegati —
scadenze superate, importi fuori soglia, valori anomali — senza che l'utente
debba chiedere. Generico per qualunque settore e sorgente dati (database o
API, vedi app.services.data_source), sullo stesso principio delle Viste
salvate (api/views.py): configurare una volta, non scrivere codice per ogni
caso.
"""
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.deps import require_admin
from app.database import get_db
from app.models.alert_rule import AlertRule
from app.models.integrations import Integration
from app.models.user import User
from app.services import alert_engine, data_source

router = APIRouter(prefix="/alerts", tags=["alerts"])

_TIPI_VALIDI = alert_engine._TIPI_VALIDI


class AzioneTemplate(BaseModel):
    """Se `to_colonna` è valorizzato, ogni segnalazione nuova di questa
    regola prepara anche una bozza pronta (vedi models.AzionePendente) —
    non solo una notifica interna. Vuoto = nessuna azione collegata."""

    to_colonna: str = ""
    oggetto_template: str = ""
    corpo_template: str = ""


class AlertRuleCreate(BaseModel):
    integration_id: int
    table_name: str
    name: str
    condition_type: str
    config: dict[str, Any] = {}
    messaggio_template: str = ""
    azione_template: AzioneTemplate = AzioneTemplate()


class AlertRuleResponse(BaseModel):
    id: int
    integration_id: int
    table_name: str
    name: str
    condition_type: str
    config: dict[str, Any]
    messaggio_template: str
    azione_template: AzioneTemplate
    attiva: bool


class Segnalazione(BaseModel):
    regola_id: int
    regola_nome: str
    pk: Any
    messaggio: str
    dettaglio: str
    integration_id: int
    table_name: str


def _to_response(rule: AlertRule) -> AlertRuleResponse:
    return AlertRuleResponse(
        id=rule.id,
        integration_id=rule.integration_id,
        table_name=rule.table_name,
        name=rule.name,
        condition_type=rule.condition_type,
        config=json.loads(rule.config),
        messaggio_template=rule.messaggio_template,
        azione_template=AzioneTemplate(**json.loads(rule.azione_template or "{}")),
        attiva=rule.attiva,
    )


def _get_owned_rule(rule_id: int, current_user: User, db: Session) -> AlertRule:
    rule = db.get(AlertRule, rule_id)
    if rule is None or rule.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regola non trovata")
    return rule


class AnteprimaRequest(BaseModel):
    integration_id: int
    table_name: str
    condition_type: str
    config: dict[str, Any] = {}


class AnteprimaResponse(BaseModel):
    totale: int
    esempi: list[str]


@router.post("/anteprima", response_model=AnteprimaResponse)
def anteprima_regola(
    payload: AnteprimaRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> AnteprimaResponse:
    """Quante righe scatterebbero ORA con questi criteri — prima ancora di
    salvare la regola, non dopo. Configurare una Segnalazione alla cieca
    (salva, poi vai a controllare altrove se ha preso qualcosa) era il punto
    più difficile segnalato dall'utente: questo chiude il giro subito,
    mentre si sta ancora scegliendo colonna/soglia."""
    if payload.condition_type not in _TIPI_VALIDI:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"condition_type deve essere uno tra {_TIPI_VALIDI}"
        )
    integration = db.get(Integration, payload.integration_id)
    if integration is None or integration.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integrazione non trovata")

    try:
        source = data_source.resolve(integration)
        risultato = data_source.list_rows(source, payload.table_name, limit=alert_engine.LIMITE_RIGHE, offset=0)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Impossibile leggere la tabella: {exc}") from exc

    grezzi = alert_engine.valuta_condizione(payload.condition_type, risultato["rows"], payload.config)
    return AnteprimaResponse(totale=len(grezzi), esempi=[g["dettaglio"] for g in grezzi[:5]])


@router.post("", response_model=AlertRuleResponse, status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: AlertRuleCreate, current_user: User = Depends(require_admin), db: Session = Depends(get_db)
) -> AlertRuleResponse:
    if payload.condition_type not in _TIPI_VALIDI:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"condition_type deve essere uno tra {_TIPI_VALIDI}"
        )
    integration = db.get(Integration, payload.integration_id)
    if integration is None or integration.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integrazione non trovata")

    rule = AlertRule(
        organization_id=current_user.organization_id,
        integration_id=payload.integration_id,
        table_name=payload.table_name,
        name=payload.name,
        condition_type=payload.condition_type,
        config=json.dumps(payload.config),
        messaggio_template=payload.messaggio_template,
        azione_template=payload.azione_template.model_dump_json(),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _to_response(rule)


@router.get("", response_model=list[AlertRuleResponse])
def list_rules(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[AlertRuleResponse]:
    rules = (
        db.query(AlertRule)
        .filter(AlertRule.organization_id == current_user.organization_id)
        .order_by(AlertRule.created_at)
        .all()
    )
    return [_to_response(r) for r in rules]


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, current_user: User = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    rule = _get_owned_rule(rule_id, current_user, db)
    db.delete(rule)
    db.commit()


@router.get("/segnalazioni", response_model=list[Segnalazione])
def get_segnalazioni(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Segnalazione]:
    """Valuta tutte le regole attive dell'azienda sui dati correnti e ritorna
    le segnalazioni scattate — calcolato al volo a ogni chiamata, non
    memorizzato: niente da segnare come "letto", la prossima chiamata
    riflette sempre lo stato vero dei dati in questo momento."""
    rules = (
        db.query(AlertRule)
        .filter(AlertRule.organization_id == current_user.organization_id, AlertRule.attiva.is_(True))
        .all()
    )
    id_a_regola = {r.id: r for r in rules}
    grezze = alert_engine.valuta_tutte_le_regole(db, current_user.organization_id)
    return [
        Segnalazione(**g, integration_id=id_a_regola[g["regola_id"]].integration_id, table_name=id_a_regola[g["regola_id"]].table_name)
        for g in grezze
    ]
