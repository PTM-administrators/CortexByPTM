"""
Una sorgente dati esplorabile può essere un database (data_explorer.py) o
un'API REST (api_connector.py). Le Viste salvate, il loro rendering e le
azioni di riga non devono sapere quale delle due stanno usando: passano
sempre da qui, che espone la stessa interfaccia a 4 funzioni per entrambe.

Aggiungere un terzo tipo di sorgente in futuro (es. un file caricato) significa
scrivere un terzo motore con questa stessa interfaccia e un ramo in più qui
sotto — non toccare le Viste, l'agente o il rendering, che restano generici.
"""
from dataclasses import dataclass
from typing import Any

from app.core.security import decrypt_credentials
from app.models.integrations import Integration
from app.services import api_connector, data_explorer
from app.services.integration_providers import get_provider_kind


@dataclass
class DataSource:
    kind: str  # "database" | "api"
    connection_string: str | None = None
    api_config: dict[str, Any] | None = None


def resolve(integration: Integration) -> DataSource:
    kind = get_provider_kind(integration.provider)
    credentials = decrypt_credentials(integration.credentials)

    if kind == "data_api":
        return DataSource(kind="api", api_config=credentials)

    connection_string = credentials.get("connection_string")
    if not connection_string:
        raise ValueError("Questa integrazione non ha dati esplorabili")
    return DataSource(kind="database", connection_string=connection_string)


def list_tables(source: DataSource) -> list[str]:
    if source.kind == "api":
        return api_connector.list_tables(source.api_config)
    return data_explorer.list_tables(source.connection_string)


def get_table_schema(source: DataSource, table_name: str) -> list[dict[str, Any]]:
    if source.kind == "api":
        return api_connector.get_table_schema(source.api_config, table_name)
    return data_explorer.get_table_schema(source.connection_string, table_name)


def list_rows(source: DataSource, table_name: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    if source.kind == "api":
        return api_connector.list_rows(source.api_config, table_name, limit, offset)
    return data_explorer.list_rows(source.connection_string, table_name, limit=limit, offset=offset)


def get_row(source: DataSource, table_name: str, pk_value: Any) -> dict[str, Any] | None:
    if source.kind == "api":
        return api_connector.get_row(source.api_config, table_name, pk_value)
    return data_explorer.get_row(source.connection_string, table_name, pk_value)
