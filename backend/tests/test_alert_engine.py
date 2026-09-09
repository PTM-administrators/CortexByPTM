"""
services/alert_engine.py: le tre condizioni di Segnalazione, valutate su
righe già in memoria (nessun database qui — logica pura, la stessa usata
sia dall'anteprima live sia dalla valutazione reale di una regola salvata).
"""
from datetime import date, timedelta

from app.services.alert_engine import valuta_condizione


def _iso(giorni_fa: int) -> str:
    return (date.today() - timedelta(days=giorni_fa)).isoformat()


class TestScadenzaSuperata:
    def test_scaduta_oltre_la_tolleranza_scatta(self) -> None:
        righe = [{"nome": "Mario", "scadenza": _iso(40)}]
        risultati = valuta_condizione(
            "scadenza_superata", righe, {"colonna_data": "scadenza", "giorni_tolleranza": 30}
        )
        assert len(risultati) == 1
        assert "10 giorni" in risultati[0]["dettaglio"]

    def test_scaduta_entro_la_tolleranza_non_scatta(self) -> None:
        righe = [{"nome": "Mario", "scadenza": _iso(20)}]
        risultati = valuta_condizione(
            "scadenza_superata", righe, {"colonna_data": "scadenza", "giorni_tolleranza": 30}
        )
        assert risultati == []

    def test_data_non_ancora_scaduta_non_scatta(self) -> None:
        righe = [{"nome": "Mario", "scadenza": (date.today() + timedelta(days=10)).isoformat()}]
        risultati = valuta_condizione("scadenza_superata", righe, {"colonna_data": "scadenza", "giorni_tolleranza": 0})
        assert risultati == []

    def test_data_mancante_o_illeggibile_non_rompe_nulla(self) -> None:
        righe = [{"nome": "Mario", "scadenza": None}, {"nome": "Luigi", "scadenza": "non-e-una-data"}]
        risultati = valuta_condizione("scadenza_superata", righe, {"colonna_data": "scadenza", "giorni_tolleranza": 0})
        assert risultati == []


class TestSogliaNumerica:
    def test_sopra_soglia_scatta(self) -> None:
        righe = [{"importo": 1500}]
        risultati = valuta_condizione("soglia_numerica", righe, {"colonna": "importo", "operatore": ">", "soglia": 1000})
        assert len(risultati) == 1

    def test_sotto_soglia_non_scatta(self) -> None:
        righe = [{"importo": 500}]
        risultati = valuta_condizione("soglia_numerica", righe, {"colonna": "importo", "operatore": ">", "soglia": 1000})
        assert risultati == []

    def test_operatore_minore_di(self) -> None:
        righe = [{"scorta": 2}, {"scorta": 50}]
        risultati = valuta_condizione("soglia_numerica", righe, {"colonna": "scorta", "operatore": "<", "soglia": 10})
        assert len(risultati) == 1


class TestValoreAnomalo:
    def test_valore_fuori_dalle_deviazioni_standard_scatta(self) -> None:
        # Campione normale intorno a 100, un outlier a 10000.
        righe = [{"importo": v} for v in (95, 100, 105, 98, 102, 10000)]
        risultati = valuta_condizione("valore_anomalo", righe, {"colonna": "importo", "soglia_deviazioni": 2})
        assert len(risultati) == 1
        assert risultati[0]["riga"]["importo"] == 10000

    def test_campione_troppo_piccolo_non_scatta_mai(self) -> None:
        """Sotto _MINIMO_CAMPIONE (4) una media/deviazione non è
        affidabile: meglio non segnalare nulla che un falso positivo."""
        righe = [{"importo": v} for v in (10, 10000)]
        risultati = valuta_condizione("valore_anomalo", righe, {"colonna": "importo", "soglia_deviazioni": 1})
        assert risultati == []

    def test_valori_tutti_uguali_non_scatta(self) -> None:
        righe = [{"importo": 100} for _ in range(5)]
        risultati = valuta_condizione("valore_anomalo", righe, {"colonna": "importo"})
        assert risultati == []

    def test_gruppi_separati_hanno_medie_separate(self) -> None:
        """Un valore normale per il gruppo A può essere anomalo per il
        gruppo B: la media va calcolata per gruppo, non su tutte le righe
        insieme. Gruppi con 6 valori "normali" (non 4, il minimo): con
        esattamente _MINIMO_CAMPIONE valori clusterizzati + 1 outlier lo
        z-score massimo raggiungibile è matematicamente < 2 per qualunque
        soglia_deviazioni=2, scoperto proprio scrivendo questo test — serve
        un campione un po' più ampio per avere margine reale."""
        righe = [
            *({"categoria": "A", "importo": v} for v in (10, 11, 9, 10, 10, 11)),
            *({"categoria": "B", "importo": v} for v in (1000, 1010, 990, 1000, 1005, 995)),
            {"categoria": "A", "importo": 5000},  # ben oltre la media/deviazione di A, normale per B
        ]
        risultati = valuta_condizione(
            "valore_anomalo", righe, {"colonna": "importo", "colonna_gruppo": "categoria", "soglia_deviazioni": 2}
        )
        assert len(risultati) == 1
        assert risultati[0]["riga"]["importo"] == 5000
