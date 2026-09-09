"""
services/esplorazione.py: l'esplorazione libera della chat su qualunque
tabella collegata. Include un test di regressione esplicito per un bug
reale trovato provando dal vivo su Trevalli il 3 settembre 2026: "VBCliente"
non si spezzava in token per mancanza di un confine minuscola→maiuscola —
senza quel test, un domani qualcuno potrebbe "semplificare" il tokenizer e
farlo tornare.
"""
from sqlalchemy import create_engine, text

from app.services import esplorazione


class TestTokenizzazione:
    def test_camel_case_normale(self) -> None:
        assert esplorazione._token("CGDatiFatturaR") == ["dati", "fattura"]

    def test_prefisso_sigla_poi_entita_regressione_vbcliente(self) -> None:
        """Il bug reale: "VBCliente" non aveva NESSUN confine
        minuscola→maiuscola (V,B,C sono tutte maiuscole prima di
        "liente") — serviva una seconda regola (sigla-poi-Parola) per
        isolare "cliente" come token utilizzabile."""
        assert "cliente" in esplorazione._token("VBCliente")

    def test_scarta_stopword_e_token_troppo_corti(self) -> None:
        token = esplorazione._token("quanti clienti abbiamo in totale")
        assert "quanti" not in token  # stopword
        assert "clienti" in token

    def test_domanda_senza_contenuto_non_produce_token(self) -> None:
        assert esplorazione._token("chi cosa come") == []  # tutte stopword


class TestMatching:
    def test_radice_comune_singolare_plurale(self) -> None:
        assert esplorazione._radice_comune("fattura", "fatture")

    def test_radice_comune_singolare_plurale_parole_corte_regressione_spesa(self) -> None:
        """Bug reale trovato dal vivo su Trevalli (3 settembre 2026): "crea
        una segnalazione per le spese maggiori di 1000 euro" non trovava
        nessuna tabella — "spesa"/"spese" sono entrambe di 5 lettere e
        differiscono solo nell'ultima, ma il confronto a prefisso pieno
        (senza scartare l'ultima lettera) richiedeva tutte e 5 uguali."""
        assert esplorazione._radice_comune("spesa", "spese")
        assert esplorazione._radice_comune("debito", "debiti")

    def test_radice_comune_non_accorcia_sotto_la_lunghezza_minima(self) -> None:
        assert not esplorazione._radice_comune("bar", "bar")  # sotto _LUNGHEZZA_MINIMA_TOKEN, mai un match

    def test_radice_comune_rifiuta_parole_di_lunghezza_molto_diversa_regressione_spesometro(self) -> None:
        """Secondo bug reale, trovato subito dopo aver corretto il primo:
        allentare il confronto per "spesa"/"spese" ha fatto anche
        combaciare "spese" con "CGSpesometroR" (un adempimento fiscale,
        non le spese) solo perché condividono le prime 4 lettere."""
        assert not esplorazione._radice_comune("spese", "spesometro")

    def test_radice_comune_rifiuta_parole_diverse(self) -> None:
        assert not esplorazione._radice_comune("cliente", "fornitore")

    def test_migliore_sceglie_il_punteggio_piu_alto(self) -> None:
        candidati = [("TabellaClienti", ["tabella", "clienti"]), ("TabellaOrdini", ["tabella", "ordini"])]
        assert esplorazione._migliore("quanti clienti abbiamo", candidati) == "TabellaClienti"

    def test_migliore_nessun_match_ritorna_none(self) -> None:
        candidati = [("TabellaClienti", ["tabella", "clienti"])]
        assert esplorazione._migliore("che tempo fa oggi", candidati) is None

    def test_migliore_nome_esatto_vince_sempre_regressione_cgdatifattura(self) -> None:
        """Bug reale trovato provando dal vivo (3 settembre 2026): cercare
        letteralmente "CGDatiFatturaR" trovava "CGDatiFatturaE" — le due
        tabelle producono lo stesso insieme di token (la lettera finale che
        le distingue è troppo corta per essere un token), quindi a parità
        di punteggio vinceva solo chi veniva prima nell'elenco."""
        candidati = [
            ("CGDatiFatturaE", ["dati", "fattura"]),
            ("CGDatiFatturaR", ["dati", "fattura"]),
            ("CGDatiFatturaT", ["dati", "fattura"]),
        ]
        assert esplorazione._migliore("CGDatiFatturaR", candidati) == "CGDatiFatturaR"

    def test_migliore_nome_esatto_case_insensitive(self) -> None:
        candidati = [("Debitori", ["debitori"])]
        assert esplorazione._migliore("debitori", candidati) == "Debitori"


class TestCerca:
    """`cerca()` con un vero (piccolo) database SQLite: verifica i due
    livelli di risposta — andamento (tabella con data+numero plausibili) e
    conteggio (tabella senza, ma comunque pertinente)."""

    # Un file temporaneo univoco per test (via la fixture pytest `tmp_path`),
    # non `:memory:`: db_engine.get_engine() cachea l'engine per connection
    # string, e un `:memory:` diverso ad ogni connessione non persisterebbe
    # i dati scritti nel setup fino alla query di `cerca()`.

    def test_trova_tabella_con_andamento(self, tmp_path) -> None:
        db_path = tmp_path / "prova_andamento.db"
        connection_string = f"sqlite:///{db_path}"
        engine = create_engine(connection_string)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE fatture (id INTEGER PRIMARY KEY, data_fattura DATE, importo NUMERIC)"))
            conn.execute(
                # Almeno 5 righe: sotto _SOGLIA_RIGHE_MINIMA in
                # analisi_automatica.py la tabella viene scartata subito,
                # prima ancora di guardarne le colonne.
                text("INSERT INTO fatture (data_fattura, importo) VALUES "
                     "('2026-01-10', 100), ('2026-01-20', 50), ('2026-02-05', 200), "
                     "('2026-02-15', 30), ('2026-02-20', 75)")
            )
            conn.commit()

        risultato = esplorazione.cerca(connection_string, "quante fatture abbiamo emesso?")
        assert risultato is not None
        assert risultato["tipo"] == "andamento"
        assert risultato["tabella"] == "fatture"

    def test_trova_tabella_solo_per_conteggio(self, tmp_path) -> None:
        db_path = tmp_path / "prova_conteggio.db"
        connection_string = f"sqlite:///{db_path}"
        engine = create_engine(connection_string)
        with engine.connect() as conn:
            # Nessuna colonna data: non può avere un "andamento", solo un conteggio.
            conn.execute(text("CREATE TABLE fornitori (id INTEGER PRIMARY KEY, ragione_sociale TEXT)"))
            for nome in ("Rossi Srl", "Bianchi Spa", "Verdi Snc"):
                conn.execute(text("INSERT INTO fornitori (ragione_sociale) VALUES (:n)"), {"n": nome})
            conn.commit()

        risultato = esplorazione.cerca(connection_string, "quanti fornitori abbiamo?")
        assert risultato is not None
        assert risultato["tipo"] == "conteggio"
        assert risultato["tabella"] == "fornitori"
        assert risultato["righe"] == 3

    def test_nessun_match_ritorna_none_onestamente(self, tmp_path) -> None:
        db_path = tmp_path / "prova_vuoto.db"
        connection_string = f"sqlite:///{db_path}"
        engine = create_engine(connection_string)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE movimenti (id INTEGER PRIMARY KEY, importo NUMERIC)"))
            conn.commit()

        assert esplorazione.cerca(connection_string, "quanti dipendenti abbiamo in azienda?") is None
