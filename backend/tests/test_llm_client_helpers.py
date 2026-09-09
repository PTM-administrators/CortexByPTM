"""
Le funzioni pure di services/llm_client.py usate dai client LLM reali
(Gemini/OpenAI) — niente chiamate di rete qui, solo le trasformazioni dati
che le circondano. I client stessi (GeminiLLMClient/OpenAILLMClient)
restano verificati manualmente con chiamate reali (vedi PLAN.md): quello
richiede una chiave API vera e ha un costo, non è automatizzabile qui.
"""
from app.services.llm_client import _contents_da_storico, _proto_a_python, _reply_di_default


class TestProtoAPython:
    def test_float_intero_diventa_int(self) -> None:
        """Bug reale trovato con Gemini: un campo dichiarato 'integer' nello
        schema (anno, mese) torna comunque come float (2026.0) — altrimenti
        date(2026.0, 7.0, 1) fallisce con TypeError più a valle."""
        assert _proto_a_python(2026.0) == 2026
        assert isinstance(_proto_a_python(2026.0), int)

    def test_float_con_virgola_resta_float(self) -> None:
        assert _proto_a_python(320.5) == 320.5

    def test_dict_annidato_convertito_ricorsivamente(self) -> None:
        class FintoStruct(dict):
            pass  # ha .items() come un vero dict, simula MapComposite di protobuf

        valore = FintoStruct(anno=2026.0, mese=7.0)
        risultato = _proto_a_python(valore)
        assert risultato == {"anno": 2026, "mese": 7}
        assert isinstance(risultato, dict)

    def test_lista_annidata_convertita_ricorsivamente(self) -> None:
        """Il caso reale che ha richiesto una conversione ricorsiva esplicita:
        "periodi": [[2026, 7], [2026, 8]] — un dict()/list() superficiale
        lascerebbe gli elementi interni ancora come oggetti protobuf."""
        risultato = _proto_a_python([[2026.0, 7.0], [2026.0, 8.0]])
        assert risultato == [[2026, 7], [2026, 8]]

    def test_stringa_non_viene_trattata_come_iterabile(self) -> None:
        """Una stringa ha __iter__ ma non va spezzata carattere per
        carattere: senza questo controllo esplicito 'ciao' diventerebbe
        ['c','i','a','o']."""
        assert _proto_a_python("ciao") == "ciao"


class TestContentsDaStorico:
    def test_messaggio_corrente_e_sempre_lultimo_turno_utente(self) -> None:
        contents = _contents_da_storico([], "quanto abbiamo in banca?")
        assert contents == [{"role": "user", "parts": ["quanto abbiamo in banca?"]}]

    def test_storico_mappato_nei_ruoli_gemini(self) -> None:
        storico = [
            {"ruolo": "utente", "testo": "spese di luglio"},
            {"ruolo": "assistente", "testo": "Ecco le spese di Luglio 2026."},
        ]
        contents = _contents_da_storico(storico, "e il mese scorso?")
        assert contents == [
            {"role": "user", "parts": ["spese di luglio"]},
            {"role": "model", "parts": ["Ecco le spese di Luglio 2026."]},
            {"role": "user", "parts": ["e il mese scorso?"]},
        ]

    def test_turni_senza_testo_vengono_scartati(self) -> None:
        storico = [{"ruolo": "assistente", "testo": ""}]
        contents = _contents_da_storico(storico, "ciao")
        assert contents == [{"role": "user", "parts": ["ciao"]}]


class TestReplyDiDefault:
    def test_visualize_tool_usa_il_testo_del_modo(self) -> None:
        assert _reply_di_default("visualize_tool", {"modo": "saldo"}) == "Ecco la liquidità attuale."

    def test_visualize_tool_modo_sconosciuto_ha_un_ripiego(self) -> None:
        assert _reply_di_default("visualize_tool", {"modo": "boh"}) != ""

    def test_email_tool_ha_un_testo_fisso(self) -> None:
        assert "conferma" in _reply_di_default("email_tool", {}).lower()

    def test_esplora_tool_ha_un_testo_fisso(self) -> None:
        assert _reply_di_default("esplora_tool", {}) != ""

    def test_tool_sconosciuto_ritorna_stringa_vuota(self) -> None:
        assert _reply_di_default("qualcosa_daltro", {}) == ""
