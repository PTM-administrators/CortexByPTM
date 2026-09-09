"""
services/vista_automatica.py e services/segnalazione_automatica.py:
"mostrami i debitori" crea da sola una Vista riusabile, "avvisami quando un
debitore è scaduto" crea da sola una Segnalazione — richiesta esplicita
dell'utente (3 settembre 2026), niente più configuratore manuale per il
caso comune.
"""
import json

import pytest
from sqlalchemy import create_engine, text

from app.services import segnalazione_automatica, vista_automatica
from tests.conftest import crea_integrazione_db, crea_organizzazione_con_admin


@pytest.fixture()
def connection_string(tmp_path) -> str:
    cs = f"sqlite:///{tmp_path / 'creazione_test.db'}"
    engine = create_engine(cs)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE debitori (id INTEGER PRIMARY KEY, nome TEXT, scadenza DATE, importo_dovuto NUMERIC)"
            )
        )
        conn.execute(
            text("INSERT INTO debitori (nome, scadenza, importo_dovuto) VALUES "
                 "('Mario Rossi', '2020-01-01', 320.5), ('Anna Neri', '2099-01-01', 89.9)")
        )
        conn.execute(text("CREATE TABLE categorie (codice TEXT PRIMARY KEY, nome TEXT)"))
        for cod in ("A1", "A2", "A3", "A4", "A5"):
            conn.execute(text("INSERT INTO categorie (codice, nome) VALUES (:c, :n)"), {"c": cod, "n": cod})
        conn.execute(text("CREATE TABLE vendite (id INTEGER PRIMARY KEY, prodotto TEXT, importo NUMERIC)"))
        # Almeno 6 valori "normali" (non solo i 4 minimi): con esattamente
        # _MINIMO_CAMPIONE valori clusterizzati + 1 outlier lo z-score
        # massimo raggiungibile è matematicamente sempre < 2 deviazioni
        # standard, qualunque sia la grandezza dell'outlier (proprietà di
        # pstdev su campioni piccoli, già scoperta scrivendo test_alert_engine.py).
        for prodotto, importo in [
            ("A", 100), ("A", 105), ("A", 95), ("A", 98), ("A", 102), ("A", 99), ("A", 10000),
        ]:
            conn.execute(
                text("INSERT INTO vendite (prodotto, importo) VALUES (:p, :i)"), {"p": prodotto, "i": importo}
            )
        conn.commit()
    return cs


@pytest.fixture()
def integration(db_session, connection_string):
    org, _admin = crea_organizzazione_con_admin(db_session)
    return crea_integrazione_db(db_session, org, connection_string)


class TestVistaAutomatica:
    def test_crea_una_vista_a_tabella_per_una_tabella_senza_data(
        self, db_session, integration, connection_string
    ) -> None:
        risultato = vista_automatica.crea_o_riusa_vista(db_session, integration, connection_string, "categorie")
        assert risultato is not None
        vista, creata_ora, nome_tabella = risultato
        assert nome_tabella == "categorie"
        assert creata_ora is True
        assert vista.mode == "table"

    def test_crea_una_vista_a_calendario_quando_ce_data_e_titolo(
        self, db_session, integration, connection_string
    ) -> None:
        risultato = vista_automatica.crea_o_riusa_vista(db_session, integration, connection_string, "debitori")
        assert risultato is not None
        vista, _creata_ora, _nome_tabella = risultato
        assert vista.mode == "calendar"
        mapping = json.loads(vista.column_mapping)
        assert mapping["data"] == "scadenza"
        assert mapping["titolo"] == "nome"

    def test_riusa_la_vista_esistente_invece_di_duplicarla(
        self, db_session, integration, connection_string
    ) -> None:
        prima = vista_automatica.crea_o_riusa_vista(db_session, integration, connection_string, "debitori")
        seconda = vista_automatica.crea_o_riusa_vista(db_session, integration, connection_string, "i debitori")
        assert prima[0].id == seconda[0].id
        assert seconda[1] is False  # non creata di nuovo

    def test_nessuna_tabella_pertinente_ritorna_none(self, db_session, integration, connection_string) -> None:
        assert vista_automatica.crea_o_riusa_vista(db_session, integration, connection_string, "dipendenti") is None


class TestSegnalazioneAutomatica:
    def test_crea_una_segnalazione_di_scadenza(self, db_session, integration, connection_string) -> None:
        risultato = segnalazione_automatica.crea_o_riusa_segnalazione_scadenza(
            db_session, integration, connection_string, "debitori scaduti"
        )
        assert risultato is not None
        regola, creata_ora, scattate = risultato
        assert creata_ora is True
        assert regola.condition_type == "scadenza_superata"
        assert len(scattate) == 1  # solo Mario Rossi (2020), non Anna Neri (2099)

    def test_riusa_la_regola_esistente(self, db_session, integration, connection_string) -> None:
        prima = segnalazione_automatica.crea_o_riusa_segnalazione_scadenza(
            db_session, integration, connection_string, "debitori"
        )
        seconda = segnalazione_automatica.crea_o_riusa_segnalazione_scadenza(
            db_session, integration, connection_string, "debitori"
        )
        assert prima[0].id == seconda[0].id
        assert seconda[1] is False

    def test_tabella_senza_colonna_data_ritorna_none(self, db_session, integration, connection_string) -> None:
        assert (
            segnalazione_automatica.crea_o_riusa_segnalazione_scadenza(
                db_session, integration, connection_string, "categorie"
            )
            is None
        )


class TestSegnalazioneAutomaticaSoglia:
    """Il caso reale che ha fatto fallire "crea una segnalazione per le
    spese maggiori di 1000 euro" (3 settembre 2026): esisteva solo il tipo
    scadenza, "soglia numerica" cadeva sempre sul vicolo cieco di
    esplora_tool ("non ho trovato dati su...")."""

    def test_crea_una_segnalazione_di_soglia(self, db_session, integration, connection_string) -> None:
        risultato = segnalazione_automatica.crea_o_riusa_segnalazione_soglia(
            db_session, integration, connection_string, "debitori", ">", 100.0
        )
        assert risultato is not None
        regola, creata_ora, scattate = risultato
        assert creata_ora is True
        assert regola.condition_type == "soglia_numerica"
        # Solo Mario Rossi (320.5) e Anna Neri (89.9 no, sotto soglia) -> solo Mario Rossi
        assert len(scattate) == 1

    def test_soglia_diversa_sulla_stessa_tabella_crea_una_regola_distinta(
        self, db_session, integration, connection_string
    ) -> None:
        """Il bug trovato scrivendo il codice: riusare in base a sola
        tabella+tipo avrebbe fatto ignorare silenziosamente una soglia
        diversa chiesta la seconda volta."""
        bassa = segnalazione_automatica.crea_o_riusa_segnalazione_soglia(
            db_session, integration, connection_string, "debitori", ">", 50.0
        )
        alta = segnalazione_automatica.crea_o_riusa_segnalazione_soglia(
            db_session, integration, connection_string, "debitori", ">", 300.0
        )
        assert bassa[0].id != alta[0].id
        assert alta[1] is True  # creata di nuovo, non riusata
        assert len(bassa[2]) == 2  # Mario Rossi (320.5) e Anna Neri (89.9), entrambi > 50
        assert len(alta[2]) == 1  # solo Mario Rossi (320.5) > 300

    def test_richiesta_identica_riusa_la_stessa_regola(self, db_session, integration, connection_string) -> None:
        prima = segnalazione_automatica.crea_o_riusa_segnalazione_soglia(
            db_session, integration, connection_string, "debitori", ">", 100.0
        )
        seconda = segnalazione_automatica.crea_o_riusa_segnalazione_soglia(
            db_session, integration, connection_string, "debitori", ">", 100.0
        )
        assert prima[0].id == seconda[0].id
        assert seconda[1] is False

    def test_tabella_senza_colonna_numerica_ritorna_none(self, db_session, integration, connection_string) -> None:
        engine = create_engine(connection_string)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE solo_testo (id INTEGER PRIMARY KEY, nome TEXT)"))
            conn.commit()
        assert (
            segnalazione_automatica.crea_o_riusa_segnalazione_soglia(
                db_session, integration, connection_string, "solo_testo", ">", 100.0
            )
            is None
        )


class TestStubLLMSegnalazioneSoglia:
    """Il riconoscimento a pattern che ha fatto scattare il bug reale:
    verifica che la frase esatta dell'utente sia ora riconosciuta."""

    def test_riconosce_la_frase_reale_dellutente(self) -> None:
        from app.services.llm import StubLLMClient

        decisione = StubLLMClient().decide_action(
            "crea una segnalazione per le spese maggiori di 1000 euro",
            {"industry": "generic", "storico": [], "ultimo_contesto_visualizzazione": None},
        )
        assert decisione.tool == "crea_segnalazione_tool"
        assert decisione.arguments["operatore"] == ">"
        assert decisione.arguments["soglia"] == 1000.0

    def test_riconosce_minore_di(self) -> None:
        from app.services.llm import StubLLMClient

        decisione = StubLLMClient().decide_action(
            "avvisami se il magazzino scende sotto 10",
            {"industry": "generic", "storico": [], "ultimo_contesto_visualizzazione": None},
        )
        assert decisione.tool == "crea_segnalazione_tool"
        assert decisione.arguments["operatore"] == "<"
        assert decisione.arguments["soglia"] == 10.0

    def test_frase_senza_parola_di_segnalazione_non_scatta(self) -> None:
        """"le spese sono maggiori di 1000" non è una richiesta di creare
        nulla, solo un'osservazione — non deve scattare il tool di
        creazione (può comunque cadere sul fallback esplora_tool)."""
        from app.services.llm import StubLLMClient

        decisione = StubLLMClient().decide_action(
            "le spese sono maggiori di 1000 rispetto al mese scorso",
            {"industry": "generic", "storico": [], "ultimo_contesto_visualizzazione": None},
        )
        assert decisione.tool != "crea_segnalazione_tool"


class TestSegnalazioneAutomaticaGenerica:
    """crea_o_riusa_segnalazione: la funzione senza casi fissati in
    anticipo, guidata da un LLM vero che ha visto le colonne reali (vedi
    AgentBrain._tabella_candidata) — richiesta esplicita dell'utente, 3
    settembre 2026: "non deve usare template predefiniti ma la chat deve
    capire qualsiasi cosa voglia l'utente"."""

    def test_valore_anomalo_prima_irraggiungibile_dalla_chat(self, db_session, integration, connection_string) -> None:
        """Prima di questa modifica non esisteva NESSUN modo di creare una
        Segnalazione di tipo valore_anomalo dalla chat — solo scadenza e
        soglia erano raggiungibili, perché erano gli unici due che
        un'espressione regolare sapeva riconoscere."""
        risultato = segnalazione_automatica.crea_o_riusa_segnalazione(
            db_session, integration, connection_string, "vendite", "valore_anomalo", colonna="importo"
        )
        assert risultato is not None
        regola, creata_ora, scattate = risultato
        assert creata_ora is True
        assert regola.condition_type == "valore_anomalo"
        assert len(scattate) == 1
        assert scattate[0]["riga"]["importo"] == 10000

    def test_colonna_scelta_dallllm_viene_validata_contro_lo_schema_reale(
        self, db_session, integration, connection_string
    ) -> None:
        """Una colonna che non esiste davvero in questa tabella (l'LLM può
        sbagliare un nome) non va mai fidata ciecamente — deve far
        ripiegare sull'euristica automatica, non rompere o usare un nome
        inventato in una query su dati veri."""
        risultato = segnalazione_automatica.crea_o_riusa_segnalazione(
            db_session, integration, connection_string, "debitori", "soglia_numerica",
            colonna="colonna_che_non_esiste", operatore=">", soglia=100.0,
        )
        assert risultato is not None
        regola, _creata_ora, _scattate = risultato
        config = json.loads(regola.config)
        assert config["colonna"] == "importo_dovuto"  # ripiegato sull'euristica, non sul nome inventato

    def test_colonna_gruppo_reale_viene_usata_se_indicata(self, db_session, integration, connection_string) -> None:
        risultato = segnalazione_automatica.crea_o_riusa_segnalazione(
            db_session, integration, connection_string, "vendite", "valore_anomalo",
            colonna="importo", colonna_gruppo="prodotto",
        )
        assert risultato is not None
        regola, _creata_ora, _scattate = risultato
        assert json.loads(regola.config)["colonna_gruppo"] == "prodotto"

    def test_colonna_gruppo_inesistente_viene_ignorata(self, db_session, integration, connection_string) -> None:
        risultato = segnalazione_automatica.crea_o_riusa_segnalazione(
            db_session, integration, connection_string, "vendite", "valore_anomalo",
            colonna="importo", colonna_gruppo="non_esiste",
        )
        assert risultato is not None
        regola, _creata_ora, _scattate = risultato
        assert "colonna_gruppo" not in json.loads(regola.config)

    def test_tipo_non_valido_ritorna_none(self, db_session, integration, connection_string) -> None:
        assert (
            segnalazione_automatica.crea_o_riusa_segnalazione(
                db_session, integration, connection_string, "debitori", "tipo_inventato"
            )
            is None
        )


class TestVistaAutomaticaConOverride:
    """crea_o_riusa_vista con mode/colonne scelti da un LLM vero, validati
    contro lo schema reale — non più solo l'euristica di base."""

    def test_override_cards_valido_viene_usato(self, db_session, integration, connection_string) -> None:
        risultato = vista_automatica.crea_o_riusa_vista(
            db_session, integration, connection_string, "debitori",
            mode="cards", colonna_titolo="nome",
        )
        assert risultato is not None
        vista, _creata_ora, _nome_tabella = risultato
        assert vista.mode == "cards"
        assert json.loads(vista.column_mapping) == {"titolo": "nome"}

    def test_override_con_colonna_inesistente_ripiega_sulleuristica(
        self, db_session, integration, connection_string
    ) -> None:
        risultato = vista_automatica.crea_o_riusa_vista(
            db_session, integration, connection_string, "debitori",
            mode="calendar", colonna_data="non_esiste", colonna_titolo="nome",
        )
        assert risultato is not None
        vista, _creata_ora, _nome_tabella = risultato
        # Non "calendar" com'era richiesto: la colonna_data indicata non
        # esiste, quindi l'intero override viene scartato e si ripiega
        # sull'euristica (che sceglie comunque "calendar", ma con la
        # colonna_data VERA trovata da sola).
        assert vista.mode == "calendar"
        assert json.loads(vista.column_mapping)["data"] == "scadenza"

    def test_mode_sconosciuto_ripiega_sulleuristica(self, db_session, integration, connection_string) -> None:
        risultato = vista_automatica.crea_o_riusa_vista(
            db_session, integration, connection_string, "categorie", mode="modalita_inventata"
        )
        assert risultato is not None
        vista, _creata_ora, _nome_tabella = risultato
        assert vista.mode == "table"
