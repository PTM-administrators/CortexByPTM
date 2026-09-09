"""
services/analisi_automatica.py: le euristiche che scelgono la colonna data e
la colonna numerica "giuste" per un andamento. Due test di regressione
espliciti per bug reali trovati provando su un database Arca vero (vedi
PLAN.md, 26 agosto 2026): senza questi, un domani qualcuno potrebbe
"semplificare" l'euristica e farli tornare.
"""
from sqlalchemy import create_engine, text

from app.services import analisi_automatica as aa


def _colonna(nome: str, tipo: str) -> dict:
    return {"name": nome, "type": tipo}


class TestColonnaData:
    def test_sceglie_una_colonna_data_plausibile(self) -> None:
        colonne = [_colonna("id", "INTEGER"), _colonna("data_scadenza", "DATE")]
        assert aa._colonna_data(colonne) == "data_scadenza"

    def test_esclude_colonne_di_audit_anche_se_sono_lunica_data(self) -> None:
        """Regressione: senza l'esclusione, una tabella con solo TimeIns
        (quando la riga è stata scritta nel database, non un fatto di
        business) veniva comunque usata per un "andamento" — un dato
        tecnico spacciato per attività reale."""
        colonne = [_colonna("id", "INTEGER"), _colonna("TimeIns", "DATETIME")]
        assert aa._colonna_data(colonne) is None

    def test_preferisce_una_data_di_business_a_una_di_audit_quando_entrambe_esistono(self) -> None:
        colonne = [_colonna("TimeIns", "DATETIME"), _colonna("DataFattura", "DATE")]
        assert aa._colonna_data(colonne) == "DataFattura"

    def test_nessuna_colonna_data_ritorna_none(self) -> None:
        colonne = [_colonna("id", "INTEGER"), _colonna("nome", "VARCHAR")]
        assert aa._colonna_data(colonne) is None


class TestColonnaNumerica:
    def test_sceglie_una_colonna_con_nome_plausibile(self) -> None:
        colonne = [_colonna("id", "INTEGER"), _colonna("Importo", "NUMERIC")]
        assert aa._colonna_numerica(colonne, set()) == "Importo"

    def test_richiede_il_prefisso_non_basta_contenere_la_parola_regressione_arca(self) -> None:
        """Il bug reale: "ContoMerceSpesa" contiene "spesa" ma è un flag
        booleano ("riga di spesa sì/no"), non un importo — la vera colonna
        importo nella stessa tabella era "ImportoE". Un match a sottostringa
        sceglieva quella sbagliata."""
        colonne = [_colonna("ContoMerceSpesa", "INTEGER"), _colonna("ImportoE", "NUMERIC")]
        assert aa._colonna_numerica(colonne, set()) == "ImportoE"

    def test_esclude_chiavi_primarie_e_colonne_id(self) -> None:
        colonne = [_colonna("Id", "INTEGER"), _colonna("CostoUnitario", "NUMERIC")]
        assert aa._colonna_numerica(colonne, {"Id"}) == "CostoUnitario"

    def test_un_intero_senza_nome_plausibile_non_e_un_importo(self) -> None:
        """A differenza della data, il tipo SQL da solo non basta: "Ordine",
        "Segno", "TipoConto" sono INTEGER ma non importi (verificato su
        dati reali)."""
        colonne = [_colonna("Ordine", "INTEGER"), _colonna("Segno", "INTEGER")]
        assert aa._colonna_numerica(colonne, set()) is None

    def test_a_parita_di_prefisso_preferisce_il_nome_piu_corto(self) -> None:
        colonne = [_colonna("ImportoPartitaV", "NUMERIC"), _colonna("Importo", "NUMERIC")]
        assert aa._colonna_numerica(colonne, set()) == "Importo"


class TestAndamentoTabella:
    """`_andamento_tabella` interroga davvero il database: qui con un
    fixture SQLite reale, non con dati finti in memoria — gli stessi due
    filtri di qualità nati da bug trovati provando su dati reali (vedi
    PLAN.md, 26 agosto 2026)."""

    def _tabella_con_righe(self, tmp_path, nome: str, righe: list[tuple[str, float]]) -> str:
        connection_string = f"sqlite:///{tmp_path / f'{nome}.db'}"
        engine = create_engine(connection_string)
        with engine.connect() as conn:
            conn.execute(text(f"CREATE TABLE {nome} (id INTEGER PRIMARY KEY, data_riga DATE, importo NUMERIC)"))
            for data_riga, importo in righe:
                conn.execute(
                    text(f"INSERT INTO {nome} (data_riga, importo) VALUES (:d, :i)"),
                    {"d": data_riga, "i": importo},
                )
            conn.commit()
        return connection_string

    def test_un_solo_mese_di_dati_non_e_un_andamento(self, tmp_path) -> None:
        connection_string = self._tabella_con_righe(
            tmp_path, "un_mese", [("2026-01-05", 100), ("2026-01-20", 50)]
        )
        engine = create_engine(connection_string)
        assert aa._andamento_tabella(engine, "un_mese", "data_riga", "importo") is None

    def test_colonna_sempre_a_zero_non_e_un_andamento(self, tmp_path) -> None:
        connection_string = self._tabella_con_righe(
            tmp_path, "sempre_zero", [("2026-01-05", 0), ("2026-02-05", 0)]
        )
        engine = create_engine(connection_string)
        assert aa._andamento_tabella(engine, "sempre_zero", "data_riga", "importo") is None

    def test_data_futura_sentinella_viene_scartata(self, tmp_path) -> None:
        """Regressione: un valore sentinella come "31/12/2070" (usato per
        "nessuna scadenza") dominava la finestra "ultimi mesi" al posto
        delle date vere (vedi CS.DataInizioAmmortamento in PLAN.md)."""
        connection_string = self._tabella_con_righe(
            tmp_path,
            "con_sentinella",
            [("2026-01-05", 100), ("2026-02-05", 50), ("2070-12-31", 999999)],
        )
        engine = create_engine(connection_string)
        andamento = aa._andamento_tabella(engine, "con_sentinella", "data_riga", "importo")
        assert andamento is not None
        assert all(p["periodo"] != "Dicembre 2070" for p in andamento)

    def test_due_mesi_con_valori_reali_e_un_andamento(self, tmp_path) -> None:
        connection_string = self._tabella_con_righe(
            tmp_path, "due_mesi", [("2026-01-05", 100), ("2026-02-05", 50)]
        )
        engine = create_engine(connection_string)
        andamento = aa._andamento_tabella(engine, "due_mesi", "data_riga", "importo")
        assert andamento is not None
        assert len(andamento) == 2
        assert sum(p["totale"] for p in andamento) == 150
