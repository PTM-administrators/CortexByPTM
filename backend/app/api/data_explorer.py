"""
Data Explorer generico: introspezione e lettura di qualunque sorgente dati
collegata tramite l'Hub Integrazioni — un database (esterno o gestito da
Cortex) o un'API REST (vedi app.services.data_source), di qualunque settore.
La stessa API serve tanto le tabelle di un ERP e-commerce quanto i Movimenti
di un tenant di finanza no-profit quanto gli annunci di un'API immobiliare:
nessuna riga di codice qui è specifica di un singolo settore, tenant o tipo
di sorgente.

La scrittura (crea/modifica/elimina riga) resta invece solo per i database:
scrivere su un'API esterna arbitraria è un'azione con effetti reali fuori da
Cortex, non una semplice lettura — se in futuro servirà, andrà pensata con lo
stesso principio di conferma esplicita già usato per le email (agent_state).
"""
import json
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel

from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.deps import get_connection_string, get_data_source, get_role_attiva, require_admin
from app.database import get_db
from app.models.membership import RUOLO_ADMIN
from app.models.user import User
from app.services import data_explorer, data_source, export_engine, import_engine

router = APIRouter(prefix="/integrations/{integration_id}", tags=["data-explorer"])

_LIMITE_EXPORT = 20_000  # generoso per i dati di un'azienda di queste dimensioni, non "tutto senza limite"


class RowWrite(BaseModel):
    values: dict[str, Any]


@router.get("/tables")
def list_tables(source: data_source.DataSource = Depends(get_data_source)) -> dict[str, list[str]]:
    try:
        return {"tables": data_source.list_tables(source)}
    except Exception as exc:  # connessione/API non raggiungibile, credenziali errate, ecc.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Impossibile leggere la sorgente dati: {exc}"
        ) from exc


@router.get("/tables/{table_name}/schema")
def get_schema(table_name: str, source: data_source.DataSource = Depends(get_data_source)) -> dict[str, list[dict]]:
    try:
        return {"columns": data_source.get_table_schema(source, table_name)}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/tables/{table_name}/rows")
def get_rows(
    table_name: str,
    limit: int = 50,
    offset: int = 0,
    source: data_source.DataSource = Depends(get_data_source),
) -> dict[str, Any]:
    try:
        return data_source.list_rows(
            source, table_name, limit=min(max(limit, 1), 200), offset=max(offset, 0)
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/tables/{table_name}/export.xlsx")
def export_table_excel(
    table_name: str, source: data_source.DataSource = Depends(get_data_source)
) -> Response:
    """Tutte le righe della tabella (fino a un limite generoso) in un file
    Excel scaricabile — generico per qualunque tabella o risorsa API, di
    qualunque settore: nessuna colonna hardcodata."""
    try:
        risultato = data_source.list_rows(source, table_name, limit=_LIMITE_EXPORT, offset=0)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    contenuto = export_engine.righe_a_excel(risultato["columns"], risultato["rows"], titolo=table_name)
    nome_file = quote(f"{table_name}.xlsx")
    return Response(
        content=contenuto,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{nome_file}"},
    )


class ImportResult(BaseModel):
    colonne_file: list[str]
    colonne_tabella: list[str]
    mapping: dict[str, str]
    anteprima: list[dict[str, Any]]
    totale: int
    valide: int
    errori: list[dict[str, Any]]
    inserite: int | None = None


@router.post("/tables/{table_name}/import", response_model=ImportResult)
async def import_table(
    table_name: str,
    file: UploadFile,
    mapping: str | None = Form(None),
    esegui: bool = Query(False),
    connection_string: str = Depends(get_connection_string),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ImportResult:
    """Carica un CSV o Excel e lo importa in questa tabella. Chiamato prima
    con esegui=False (anteprima: mapping suggerito, righe valide/errate, nulla
    scritto — aperta anche a un utente sola lettura, non scrive nulla) e poi
    con esegui=True (lo stesso file, lo stesso mapping magari corretto
    dall'utente — questa volta scrive davvero, richiede admin). Solo per
    database: scrivere su un'API esterna arbitraria non è supportato, per lo
    stesso motivo per cui non lo è la scrittura generica del Data Explorer."""
    if esegui and get_role_attiva(db, current_user) != RUOLO_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Serve un ruolo di amministratore per questa azione."
        )
    contenuto = await file.read()
    try:
        intestazioni, righe_file = import_engine.parse_file(file.filename or "import.csv", contenuto)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"File non leggibile: {exc}") from exc
    if not righe_file:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Il file non contiene righe da importare.")

    try:
        schema = data_explorer.get_table_schema(connection_string, table_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    colonne_tabella = [c["name"] for c in schema if not c["primary_key"]]

    mapping_scelto = json.loads(mapping) if mapping else import_engine.suggerisci_mapping(intestazioni, colonne_tabella)
    righe_preparate = import_engine.prepara_righe(righe_file, mapping_scelto)
    risultato = import_engine.importa(connection_string, table_name, righe_preparate, esegui=esegui)

    return ImportResult(
        colonne_file=intestazioni,
        colonne_tabella=colonne_tabella,
        mapping=mapping_scelto,
        anteprima=righe_preparate[:10],
        **risultato,
    )


@router.post("/tables/{table_name}/rows", status_code=status.HTTP_201_CREATED)
def create_row(
    table_name: str,
    payload: RowWrite,
    connection_string: str = Depends(get_connection_string),
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return data_explorer.insert_row(connection_string, table_name, payload.values)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/tables/{table_name}/rows/{pk_value}")
def update_row(
    table_name: str,
    pk_value: str,
    payload: RowWrite,
    connection_string: str = Depends(get_connection_string),
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return data_explorer.update_row(connection_string, table_name, pk_value, payload.values)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/tables/{table_name}/rows/{pk_value}", status_code=status.HTTP_204_NO_CONTENT)
def delete_row(
    table_name: str,
    pk_value: str,
    connection_string: str = Depends(get_connection_string),
    _admin: User = Depends(require_admin),
) -> None:
    try:
        data_explorer.delete_row(connection_string, table_name, pk_value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
