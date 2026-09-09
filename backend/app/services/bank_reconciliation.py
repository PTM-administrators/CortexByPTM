"""
Riconciliazione bancaria: abbina le righe di un estratto conto importato ai
Movimenti già registrati su conto "Banca", segnalando solo le differenze —
invece di dover ricontrollare tutto a mano (Sezione 6 del piano di progetto).

Abbinamento per importo esatto e data entro una tolleranza (default 3 giorni):
non confronta le descrizioni, solo importo/data — un primo modello, pensato
per il caso comune di un pagamento registrato con qualche giorno di scarto
rispetto a quando la banca lo elabora davvero. Da raffinare se in pratica
capitano troppi falsi abbinamenti (es. più movimenti con lo stesso importo
nello stesso periodo).
"""
import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, select

from app.services import db_templates


@dataclass
class RigaEstrattoConto:
    data: date
    importo: Decimal
    descrizione: str


_ALIAS_COLONNE = {
    "data": {"data", "date"},
    "importo": {"importo", "amount", "importo (eur)", "importo eur", "valore"},
    "descrizione": {"descrizione", "causale", "description", "note", "memo"},
}


def _trova_colonna(fieldnames: list[str], alias: set[str]) -> str | None:
    for name in fieldnames:
        if name.strip().lower() in alias:
            return name
    return None


def _parse_data(raw: str) -> date:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"data non riconosciuta: '{raw}' (formati supportati: AAAA-MM-GG, GG/MM/AAAA)")


def _parse_importo(raw: str) -> Decimal:
    pulito = raw.strip().replace("€", "").replace(" ", "")
    if "," in pulito and "." in pulito:  # formato italiano 1.234,56
        pulito = pulito.replace(".", "").replace(",", ".")
    elif "," in pulito:  # 12,34 -> 12.34
        pulito = pulito.replace(",", ".")
    try:
        return Decimal(pulito)
    except InvalidOperation as exc:
        raise ValueError(f"importo non riconosciuto: '{raw}'") from exc


def parse_estratto_conto_csv(contenuto: str) -> list[RigaEstrattoConto]:
    """Legge un CSV con colonne data/importo/descrizione (nomi flessibili,
    vedi _ALIAS_COLONNE — pensato per essere facile da esportare da un
    qualunque home banking, non per un tracciato bancario specifico)."""
    reader = csv.DictReader(io.StringIO(contenuto))
    if not reader.fieldnames:
        raise ValueError("il file è vuoto o non è un CSV valido")

    colonna_data = _trova_colonna(reader.fieldnames, _ALIAS_COLONNE["data"])
    colonna_importo = _trova_colonna(reader.fieldnames, _ALIAS_COLONNE["importo"])
    colonna_descrizione = _trova_colonna(reader.fieldnames, _ALIAS_COLONNE["descrizione"])

    mancanti = [nome for nome, col in [("data", colonna_data), ("importo", colonna_importo)] if col is None]
    if mancanti:
        raise ValueError(
            f"colonne mancanti nel CSV: {', '.join(mancanti)}. Intestazioni trovate: {reader.fieldnames}"
        )

    righe: list[RigaEstrattoConto] = []
    for numero_riga, riga in enumerate(reader, start=2):  # la riga 1 è l'intestazione
        try:
            righe.append(
                RigaEstrattoConto(
                    data=_parse_data(riga[colonna_data]),
                    importo=_parse_importo(riga[colonna_importo]),
                    descrizione=(riga.get(colonna_descrizione) or "").strip() if colonna_descrizione else "",
                )
            )
        except ValueError as exc:
            raise ValueError(f"riga {numero_riga}: {exc}") from exc
    return righe


def _engine(connection_string: str):
    return create_engine(connection_string)


def _reflect(engine: Any, table_name: str) -> Table:
    return Table(table_name, MetaData(), autoload_with=engine)


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _serializza(movimento: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": movimento["id"],
        "data": _as_date(movimento["data"]).isoformat(),
        "importo": float(_as_decimal(movimento["importo"])),
        "descrizione": movimento["descrizione"],
        "categoria_codice": movimento["categoria_codice"],
    }


def reconcile(
    connection_string: str, righe: list[RigaEstrattoConto], tolleranza_giorni: int = 3
) -> dict[str, Any]:
    # I database provisionati prima che 'riconciliato' esistesse nel template
    # non ce l'hanno ancora: la aggiunge se manca, senza dover riprovisionare.
    db_templates.add_riconciliato_column_if_missing(connection_string)

    engine = _engine(connection_string)
    try:
        movimenti = _reflect(engine, "movimenti")
        with engine.connect() as conn:
            disponibili = [
                dict(row._mapping)
                for row in conn.execute(
                    select(movimenti).where(movimenti.c.conto == "Banca", movimenti.c.riconciliato.is_(False))
                )
            ]

        abbinati: list[dict[str, Any]] = []
        solo_estratto: list[dict[str, Any]] = []
        id_da_marcare: list[int] = []

        for riga in righe:
            miglior_match: dict[str, Any] | None = None
            miglior_distanza: int | None = None
            for movimento in disponibili:
                if _as_decimal(movimento["importo"]) != riga.importo:
                    continue
                distanza = abs((_as_date(movimento["data"]) - riga.data).days)
                if distanza > tolleranza_giorni:
                    continue
                if miglior_distanza is None or distanza < miglior_distanza:
                    miglior_match, miglior_distanza = movimento, distanza

            if miglior_match is not None:
                disponibili.remove(miglior_match)
                id_da_marcare.append(miglior_match["id"])
                abbinati.append(
                    {
                        "estratto": {
                            "data": riga.data.isoformat(),
                            "importo": float(riga.importo),
                            "descrizione": riga.descrizione,
                        },
                        "movimento": _serializza(miglior_match),
                    }
                )
            else:
                solo_estratto.append(
                    {"data": riga.data.isoformat(), "importo": float(riga.importo), "descrizione": riga.descrizione}
                )

        if id_da_marcare:
            with engine.begin() as conn:
                conn.execute(movimenti.update().where(movimenti.c.id.in_(id_da_marcare)).values(riconciliato=True))

        return {
            "abbinati": abbinati,
            # nell'estratto conto ma non tra i movimenti: forse da registrare in Prima Nota
            "solo_estratto": solo_estratto,
            # tra i movimenti ma non nell'estratto: forse non ancora passato in banca (es. assegno
            # non incassato), o un errore di registrazione da controllare
            "solo_movimenti": [_serializza(m) for m in disponibili],
        }
    finally:
        engine.dispose()
