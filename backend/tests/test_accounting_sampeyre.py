"""
services/accounting_engine.py (profilo Sampeyre): saldi, spese per
categoria, andamento mensile, ultimo periodo con movimenti — su un piccolo
database SQLite reale con lo schema esatto atteso (tabelle `movimenti` e
`categorie`), non su dati finti in memoria. Il profilo Arca
(accounting_engine_arca.py) non è testato qui: richiede un vero SQL Server,
volutamente fuori dalla portata di una suite di test automatica veloce — per
quello resta la verifica manuale già in uso (vedi PLAN.md).
"""
import pytest
from sqlalchemy import create_engine, text

from app.services import accounting_engine as ae


@pytest.fixture()
def connection_string(tmp_path) -> str:
    cs = f"sqlite:///{tmp_path / 'sampeyre_test.db'}"
    engine = create_engine(cs)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE categorie (codice TEXT PRIMARY KEY, nome TEXT, tipo TEXT)"))
        conn.execute(
            text("CREATE TABLE movimenti (id INTEGER PRIMARY KEY, data DATE, descrizione TEXT, conto TEXT, "
                 "importo NUMERIC, categoria_codice TEXT)")
        )
        conn.execute(
            text("INSERT INTO categorie (codice, nome, tipo) VALUES "
                 "('E1', 'Donazioni', 'entrata'), ('U1', 'Energia elettrica', 'uscita'), "
                 "('U2', 'Spese telefoniche', 'uscita')")
        )
        righe = [
            ("2026-06-05", "Donazione giugno", "Banca", 1000, "E1"),
            ("2026-06-10", "Bolletta luce giugno", "Banca", 148, "U1"),
            ("2026-06-15", "Bolletta telefono giugno", "Banca", 45, "U2"),
            ("2026-07-05", "Donazione luglio", "Banca", 800, "E1"),
            ("2026-07-10", "Bolletta luce luglio", "Banca", 152, "U1"),
            ("2026-07-15", "Bolletta telefono luglio", "Banca", 42, "U2"),
        ]
        for data, descr, conto, importo, cat in righe:
            conn.execute(
                text(
                    "INSERT INTO movimenti (data, descrizione, conto, importo, categoria_codice) "
                    "VALUES (:d, :descr, :conto, :importo, :cat)"
                ),
                {"d": data, "descr": descr, "conto": conto, "importo": importo, "cat": cat},
            )
        conn.commit()
    return cs


def test_compute_saldi_somma_entrate_e_sottrae_uscite(connection_string: str) -> None:
    saldi = ae.compute_saldi(connection_string)
    # Entrate totali 1800, uscite totali (148+45+152+42)=387 -> saldo Banca 1413
    assert saldi["Banca"] == pytest.approx(1413.0)
    assert saldi["Cassa"] == 0.0
    assert saldi["Titoli"] == 0.0


def test_compute_spese_per_categoria_filtra_per_mese_e_tipo(connection_string: str) -> None:
    spese_luglio = ae.compute_spese_per_categoria(connection_string, 2026, 7, "uscita")
    per_codice = {r["categoria_codice"]: r["totale"] for r in spese_luglio}
    assert per_codice == {"U1": 152.0, "U2": 42.0}


def test_compute_spese_per_categoria_non_mescola_entrate_e_uscite(connection_string: str) -> None:
    entrate_luglio = ae.compute_spese_per_categoria(connection_string, 2026, 7, "entrata")
    assert [r["categoria_codice"] for r in entrate_luglio] == ["E1"]
    assert entrate_luglio[0]["totale"] == 800.0


def test_compute_andamento_mensile_copre_tutti_i_12_mesi(connection_string: str) -> None:
    andamento = ae.compute_andamento_mensile(connection_string, 2026, "uscita")
    assert len(andamento) == 12
    per_mese = {r["mese"]: r["totale"] for r in andamento}
    assert per_mese[6] == pytest.approx(193.0)  # 148 + 45
    assert per_mese[7] == pytest.approx(194.0)  # 152 + 42
    assert per_mese[1] == 0.0  # nessun movimento a gennaio


def test_list_movimenti_filtra_per_mese_e_tipo(connection_string: str) -> None:
    righe = ae.list_movimenti(connection_string, 2026, 6, "uscita")
    assert len(righe) == 2
    assert {r["categoria"] for r in righe} == {"Energia elettrica", "Spese telefoniche"}


def test_list_movimenti_senza_tipo_mostra_tutto(connection_string: str) -> None:
    righe = ae.list_movimenti(connection_string, 2026, 6, None)
    assert len(righe) == 3  # 1 entrata + 2 uscite di giugno


def test_ultimo_periodo_con_movimenti(connection_string: str) -> None:
    assert ae.ultimo_periodo_con_movimenti(connection_string) == (2026, 7)


def test_ultimo_periodo_con_movimenti_none_se_tabella_vuota(tmp_path) -> None:
    cs = f"sqlite:///{tmp_path / 'vuoto.db'}"
    engine = create_engine(cs)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE categorie (codice TEXT PRIMARY KEY, nome TEXT, tipo TEXT)"))
        conn.execute(
            text("CREATE TABLE movimenti (id INTEGER PRIMARY KEY, data DATE, descrizione TEXT, conto TEXT, "
                 "importo NUMERIC, categoria_codice TEXT)")
        )
        conn.commit()
    assert ae.ultimo_periodo_con_movimenti(cs) is None
