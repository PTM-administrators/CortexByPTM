"""
StubLLMClient (vedi app/services/llm_client.py): il riconoscimento a pattern
gratuito che decide cosa deve fare l'agente quando non c'è un LLM vero
configurato (o quando quello vero fallisce — vedi AgentBrain._decidi_con_ripiego).
Logica pura, nessun database o rete: veloce da testare a fondo, ed è
esattamente la parte che regge la chat quando la quota di Gemini è esaurita
— vale la pena che sia solida.
"""
from datetime import date

from app.services.llm import StubLLMClient

_CONTESTO_VUOTO = {"industry": "generic", "storico": [], "ultimo_contesto_visualizzazione": None}


def decidi(messaggio: str, **contesto_extra) -> object:
    contesto = {**_CONTESTO_VUOTO, **contesto_extra}
    return StubLLMClient().decide_action(messaggio, contesto)


def test_saldo() -> None:
    d = decidi("quanto abbiamo in banca?")
    assert d.tool == "visualize_tool"
    assert d.arguments["modo"] == "saldo"


def test_periodo_singolo_mese() -> None:
    d = decidi("mostrami le spese di luglio 2026")
    assert d.arguments["modo"] == "periodo"
    assert d.arguments["tipo"] == "uscita"
    assert d.arguments["periodi"] == [(2026, 7)]


def test_periodo_entrate_esplicite() -> None:
    d = decidi("mostrami le entrate di marzo 2025")
    assert d.arguments["tipo"] == "entrata"


def test_confronto_due_mesi() -> None:
    d = decidi("confronta le spese di luglio 2026 con maggio 2026")
    assert d.arguments["modo"] == "confronto"
    assert d.arguments["periodi"] == [(2026, 7), (2026, 5)]


def test_composizione() -> None:
    d = decidi("composizione delle spese di agosto 2026")
    assert d.arguments["modo"] == "periodo"
    assert d.arguments["composizione"] is True


def test_andamento_senza_anno_usa_anno_corrente() -> None:
    d = decidi("andamento delle entrate")
    assert d.arguments["modo"] == "andamento"
    assert d.arguments["anno"] == date.today().year


def test_elenco_movimenti() -> None:
    d = decidi("dammi i movimenti di luglio 2026")
    assert d.arguments["modo"] == "elenco"
    assert d.arguments["periodi"] == [(2026, 7)]


def test_spiegazione_senza_mese_usa_mese_corrente() -> None:
    d = decidi("perché sono aumentate le spese?")
    oggi = date.today()
    assert d.arguments["modo"] == "spiegazione"
    assert d.arguments["periodi"] == [(oggi.year, oggi.month)]


def test_quadro_generale() -> None:
    d = decidi("come sta andando l'azienda?")
    assert d.arguments["modo"] == "quadro_generale"


def test_quadro_generale_vince_su_saldo_quando_entrambi_matchano() -> None:
    """"panoramica sulla liquidità" contiene sia una parola del quadro
    generale sia una del saldo — deve vincere il quadro generale, la
    lettura più ricca delle due (vedi commento in llm_client.py)."""
    d = decidi("panoramica sulla liquidità")
    assert d.arguments["modo"] == "quadro_generale"


class TestEmail:
    def test_email_completa(self) -> None:
        d = decidi("manda una email a mario@esempio.it dicendo: ciao Mario")
        assert d.tool == "email_tool"
        assert d.arguments["to_address"] == "mario@esempio.it"
        assert d.arguments["body"] == "ciao Mario"
        assert not d.missing_fields

    def test_email_senza_destinatario(self) -> None:
        d = decidi("manda un'email dicendo: ciao")
        assert d.tool == "email_tool"
        assert "destinatario" in d.missing_fields

    def test_email_da_istruzione_indiretta(self) -> None:
        d = decidi("scrivi a mario@esempio.it in cui gli dici di richiamarmi")
        assert d.arguments["to_address"] == "mario@esempio.it"
        assert "richiamarmi" in d.arguments["body"]


def test_ricerca_online() -> None:
    d = decidi("cerca il numero di telefono del fornitore XY")
    assert d.tool == "scraper_tool"
    assert d.arguments["query"] == "cerca il numero di telefono del fornitore XY"


class TestSalutiEFallback:
    def test_saluto_non_cerca_nei_dati(self) -> None:
        d = decidi("ciao")
        assert d.tool == "none"

    def test_messaggio_di_sola_cortesia_non_cerca_nei_dati(self) -> None:
        d = decidi("grazie")
        assert d.tool == "none"

    def test_domanda_fuori_dai_modi_fissi_va_a_esplora_tool(self) -> None:
        """Prima della modifica del 3 settembre 2026 questo cadeva su un
        "none" fisso — la stessa richiesta di "chat inutile" che ha portato
        a costruire l'esplorazione libera (services/esplorazione.py)."""
        d = decidi("quanti fornitori abbiamo?")
        assert d.tool == "esplora_tool"
        assert d.arguments["termine"] == "quanti fornitori abbiamo?"


class TestRiferimentoRelativo:
    """"e il mese scorso?" ha senso solo con memoria della richiesta
    precedente (vedi services/conversation_state, passata qui in
    ultimo_contesto_visualizzazione)."""

    def test_senza_contesto_precedente_non_lo_tratta_come_un_periodo(self) -> None:
        """Senza un contesto precedente non c'è modo di sapere "il mese
        scorso rispetto a cosa": non deve inventarsi un modo visualize_tool
        — può comunque cadere sul fallback esplora_tool generico, che
        risponderà onestamente di non aver trovato nulla."""
        d = decidi("e il mese scorso?")
        assert d.tool != "visualize_tool"

    def test_con_contesto_precedente_sposta_il_periodo_indietro(self) -> None:
        d = decidi(
            "e il mese scorso?",
            ultimo_contesto_visualizzazione={"modo": "periodo", "tipo": "uscita", "periodi": [[2026, 7]]},
        )
        assert d.arguments["modo"] == "periodo"
        assert d.arguments["periodi"] == [[2026, 6]]

    def test_riferimento_relativo_gestisce_il_cambio_danno_a_gennaio(self) -> None:
        d = decidi(
            "il mese scorso",
            ultimo_contesto_visualizzazione={"modo": "elenco", "tipo": None, "periodi": [[2026, 1]]},
        )
        assert d.arguments["periodi"] == [[2025, 12]]

    def test_non_si_applica_a_un_confronto(self) -> None:
        """Un "confronto" ha già due periodi: "il mese scorso" da solo non
        ha un modo univoco di applicarsi, meglio non riconoscerlo che
        indovinare male."""
        d = decidi(
            "e il mese scorso?",
            ultimo_contesto_visualizzazione={
                "modo": "confronto",
                "tipo": "uscita",
                "periodi": [[2026, 7], [2026, 5]],
            },
        )
        assert d.tool != "visualize_tool" or d.arguments.get("modo") != "periodo"
