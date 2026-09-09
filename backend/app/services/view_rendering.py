"""
Formatta le righe di una sorgente dati collegata (database o API REST — vedi
app.services.data_source) secondo la modalità di una Vista salvata
(tabella/schede/calendario) — condiviso tra l'endpoint GET /views/{id}/data e
l'agente, che richiama una vista salvata per nome dalla chat (vedi
agent_brain.py._try_saved_view): stessa resa, due punti d'ingresso diversi
(form o chat).
"""
import json
from typing import Any

from app.models.saved_view import SavedView
from app.services.data_source import DataSource, list_rows as _list_rows

LIMITE_RIGHE = 200  # abbastanza per una vista (tabella/schede/calendario), non l'intero db

_MODI_VALIDI = ("table", "cards", "calendar")


def render_view_data(view: SavedView, source: DataSource) -> dict[str, Any]:
    mapping = json.loads(view.column_mapping)
    row_actions = json.loads(view.row_actions)

    risultato = _list_rows(source, view.table_name, limit=LIMITE_RIGHE, offset=0)
    righe, pk = risultato["rows"], risultato["primary_key"]

    if view.mode == "table":
        return {
            "type": "table",
            "title": view.name,
            "columns": [{"key": c, "label": c} for c in risultato["columns"]],
            "rows": righe,
            "primary_key": pk,
            "actions": [{"name": a["nome"]} for a in row_actions],
            # Presente solo quando il widget arriva da una vista salvata (non
            # da visualize_tool): il frontend lo usa per sapere a quale vista
            # rivolgere il trigger di un'azione riga (vedi Dashboard.jsx).
            "view_id": view.id,
        }

    if view.mode == "cards":
        colonna_titolo = mapping.get("titolo")
        return {
            "type": "entity_cards",
            "title": view.name,
            "primary_key": pk,
            # Come per "table": presente solo da vista salvata, usato dal
            # frontend per recuperare il dettaglio completo di una scheda
            # (GET /views/{view_id}/rows/{pk}) quando viene espansa.
            "view_id": view.id,
            "items": [
                {
                    "_pk": r.get(pk),
                    "titolo": r.get(colonna_titolo, ""),
                    "sottotitolo": r.get(mapping.get("sottotitolo", "")),
                    "badge": r.get(mapping.get("badge", "")),
                }
                for r in righe
            ],
        }

    if view.mode == "calendar":
        colonna_data = mapping.get("data")
        colonna_titolo = mapping.get("titolo")
        return {
            "type": "calendar",
            "title": view.name,
            "events": [
                {"data": str(r.get(colonna_data, ""))[:10], "titolo": r.get(colonna_titolo, "")}
                for r in righe
                if r.get(colonna_data)
            ],
        }

    raise ValueError(f"Modalità sconosciuta: {view.mode}")
