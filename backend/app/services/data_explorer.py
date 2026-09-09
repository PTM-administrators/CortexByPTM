"""
Motore generico di esplorazione dati: dato il connection_string di un'integrazione
(esterna o gestita da Cortex, non importa quale), permette di elencare tabelle,
leggerne lo schema e fare CRUD sulle righe — qualunque sia la forma dei dati.

Usato dal Data Explorer del frontend, disponibile a ogni tenant di ogni settore:
lo stesso codice mostra le tabelle di un ERP e-commerce o i Movimenti di Sampeyre.

Sicurezza: nomi di tabella/colonna non vengono MAI concatenati in SQL. Si passa
sempre dalla reflection di SQLAlchemy (`Table(..., autoload_with=engine)`), che
legge la tabella dal catalogo del database stesso, e i valori vengono passati
sempre come parametri tramite l'API Core di SQLAlchemy (mai stringhe formattate).
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Table, func, select

from app.services import db_engine


def _engine_for(connection_string: str):
    # Engine cacheato e riusato (vedi app.services.db_engine) — non più uno
    # nuovo per ogni chiamata: creare/chiudere una connessione a un database
    # aziendale reale ad ogni singola richiesta HTTP è costoso ed è parte
    # del motivo per cui "ogni caricamento" risultava lento.
    return db_engine.get_engine(connection_string)


def list_tables(connection_string: str) -> list[str]:
    return db_engine.list_table_names(_engine_for(connection_string))


def _reflect_table(engine: Any, table_name: str) -> Table:
    # Whitelist: il nome tabella deve comparire tra quelli letti dal catalogo del
    # database. Evita di passare nomi arbitrari a Table()/autoload, che andrebbe
    # comunque a leggere solo tabelle realmente esistenti, ma così l'errore è
    # esplicito e non dipende dal comportamento del dialetto SQL in uso.
    existing = db_engine.list_table_names(engine)
    if table_name not in existing:
        raise ValueError(f"Tabella '{table_name}' non trovata in questo database")
    # Tabella riflessa cacheata (vedi app.services.db_engine): la vera causa
    # della lentezza misurata — 16 secondi su una singola tabella larga di
    # un database Arca reale, rifatti ad ogni chiamata prima di questo fix.
    return db_engine.get_reflected_table(engine, table_name)


def _primary_key_column(table: Table) -> str:
    pk_columns = list(table.primary_key.columns)
    if not pk_columns:
        raise ValueError("Questa tabella non ha una chiave primaria: non è modificabile da qui")
    return pk_columns[0].name


def _colonne_ordinamento(table: Table) -> list[Any]:
    """Colonne su cui ordinare una lettura paginata: la chiave primaria se
    c'è, altrimenti la prima colonna della tabella. SQLite e PostgreSQL
    accettano LIMIT/OFFSET senza ORDER BY (risultato "quello che capita", non
    garantito stabile) — SQL Server invece lo *richiede* esplicitamente,
    quindi qui non è opzionale: senza, la query fallisce con un errore SQL
    poco chiaro invece di un risultato. Scoperto collegando un vero database
    Arca (SQL Server) durante lo sviluppo."""
    pk_columns = list(table.primary_key.columns)
    if pk_columns:
        return pk_columns
    tutte = list(table.columns)
    return [tutte[0]] if tutte else []


def _valore_serializzabile(valore: Any) -> Any:
    """SQL Server usa spesso una colonna binaria (tipo `rowversion`/
    `timestamp`, per il controllo di concorrenza — qui vista come "Ts" in un
    database Arca reale) che arriva come `bytes` Python: FastAPI non sa
    convertirla in JSON e l'intera risposta fallisce con un errore generico,
    anche se la query è andata a buon fine. Resa leggibile come stringa
    esadecimale invece di far fallire tutta la riga."""
    if isinstance(valore, bytes):
        return valore.hex()
    return valore


def _riga_a_dict(mapping: Any) -> dict[str, Any]:
    return {chiave: _valore_serializzabile(valore) for chiave, valore in dict(mapping).items()}


def _coerce_value(raw_value: Any, column: Any) -> Any:
    """Converte un valore arrivato dal frontend (sempre stringa, dato che viene
    da un <input>) nel tipo Python che la colonna si aspetta: SQLAlchemy non lo
    fa da solo (es. SQLite rifiuta una stringa su una colonna Date). Necessario
    perché questo motore è generico e non conosce in anticipo lo schema."""
    if raw_value is None:
        return None
    if isinstance(raw_value, str) and raw_value.strip() == "":
        return None  # campo lasciato vuoto nel form -> NULL, non stringa vuota

    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return raw_value  # tipo di colonna esotico senza python_type: lascialo passare

    if isinstance(raw_value, python_type):
        return raw_value

    text = str(raw_value).strip()
    try:
        if python_type is bool:
            return text.lower() in ("1", "true", "on", "yes", "si", "sì")
        if python_type is date:
            return date.fromisoformat(text[:10])
        if python_type is datetime:
            return datetime.fromisoformat(text)
        if python_type is Decimal:
            return Decimal(text)
        return python_type(text)
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(f"Valore non valido per '{column.name}': {raw_value!r}") from exc


def _coerce_payload(table: Table, payload: dict[str, Any]) -> dict[str, Any]:
    return {key: _coerce_value(value, table.c[key]) for key, value in payload.items()}


def validate_row(connection_string: str, table_name: str, values: dict[str, Any]) -> dict[str, Any]:
    """Converte i valori nei tipi attesi dalla tabella SENZA scriverli —
    usato dall'import (app.services.import_engine) per controllare che una
    riga sia valida prima di inserirla davvero, così un file con 500 righe
    di cui 3 sbagliate non deve essere corretto e ricaricato da zero: si
    vede subito quali 3 e perché."""
    engine = _engine_for(connection_string)
    table = _reflect_table(engine, table_name)
    known_columns = set(table.columns.keys())
    payload = {k: v for k, v in values.items() if k in known_columns}
    return _coerce_payload(table, payload)


def get_table_schema(connection_string: str, table_name: str) -> list[dict[str, Any]]:
    engine = _engine_for(connection_string)
    table = _reflect_table(engine, table_name)
    return [
        {
            "name": col.name,
            "type": str(col.type),
            "nullable": col.nullable,
            "primary_key": col.primary_key,
        }
        for col in table.columns
    ]


def list_rows(connection_string: str, table_name: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    engine = _engine_for(connection_string)
    table = _reflect_table(engine, table_name)
    with engine.connect() as conn:
        total = conn.execute(select(func.count()).select_from(table)).scalar_one()
        query = select(table).order_by(*_colonne_ordinamento(table)).limit(limit).offset(offset)
        result = conn.execute(query)
        rows = [_riga_a_dict(row._mapping) for row in result]
    return {
        "columns": [c.name for c in table.columns],
        "primary_key": _primary_key_column(table),
        "rows": rows,
        "total": total,
    }


def get_row(connection_string: str, table_name: str, pk_value: Any) -> dict[str, Any] | None:
    """Legge una singola riga per chiave primaria — usata dalle Viste salvate
    per costruire un'azione personalizzata (es. email di sollecito) a partire
    dai valori reali di quella riga."""
    engine = _engine_for(connection_string)
    table = _reflect_table(engine, table_name)
    pk_name = _primary_key_column(table)
    with engine.connect() as conn:
        row = conn.execute(select(table).where(table.c[pk_name] == pk_value)).mappings().first()
    return _riga_a_dict(row) if row is not None else None


def insert_row(connection_string: str, table_name: str, values: dict[str, Any]) -> dict[str, Any]:
    engine = _engine_for(connection_string)
    table = _reflect_table(engine, table_name)
    known_columns = set(table.columns.keys())
    payload = _coerce_payload(table, {k: v for k, v in values.items() if k in known_columns})
    if not payload:
        raise ValueError("Nessun campo valido da inserire")

    pk_name = _primary_key_column(table)
    with engine.begin() as conn:
        result = conn.execute(table.insert().values(**payload))
        new_id = result.inserted_primary_key[0] if result.inserted_primary_key else None
        row = None
        if new_id is not None:
            row = conn.execute(select(table).where(table.c[pk_name] == new_id)).mappings().first()
    return _riga_a_dict(row) if row is not None else payload


def update_row(connection_string: str, table_name: str, pk_value: Any, values: dict[str, Any]) -> dict[str, Any]:
    engine = _engine_for(connection_string)
    table = _reflect_table(engine, table_name)
    pk_name = _primary_key_column(table)
    known_columns = set(table.columns.keys()) - {pk_name}
    payload = _coerce_payload(table, {k: v for k, v in values.items() if k in known_columns})
    if not payload:
        raise ValueError("Nessun campo valido da aggiornare")

    with engine.begin() as conn:
        result = conn.execute(table.update().where(table.c[pk_name] == pk_value).values(**payload))
        if result.rowcount == 0:
            raise ValueError("Riga non trovata")
        row = conn.execute(select(table).where(table.c[pk_name] == pk_value)).mappings().first()
    return _riga_a_dict(row)


def delete_row(connection_string: str, table_name: str, pk_value: Any) -> None:
    engine = _engine_for(connection_string)
    table = _reflect_table(engine, table_name)
    pk_name = _primary_key_column(table)
    with engine.begin() as conn:
        result = conn.execute(table.delete().where(table.c[pk_name] == pk_value))
    if result.rowcount == 0:
        raise ValueError("Riga non trovata")
