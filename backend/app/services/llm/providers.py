from __future__ import annotations
from typing import Any
from app.services.llm.core import AgentDecision
from app.services.llm.tools_schema import _function_declarations, _istruzioni_sistema, _reply_di_default

class OpenAILLMClient:
    """Client reale (OpenAI, function calling). Scritta per essere pronta
    all'uso ma NON ancora collaudata in questa sessione: nessuna chiave era
    configurata (vedi PLAN.md, 12 agosto 2026). Verificare con una chiamata
    reale prima di affidarcisi in produzione."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._api_key = api_key
        self._model = model

    def decide_action(self, message: str, context: dict[str, Any]) -> AgentDecision:
        from openai import OpenAI  # import differito: pesante e non necessario in modalità stub

        # Timeout esplicito (vedi anche GeminiLLMClient, stessa ragione):
        # senza, una risposta lenta o un rate-limit lato provider blocca la
        # richiesta HTTP a tempo indeterminato invece di far scattare il
        # ripiego su StubLLMClient (AgentBrain._decidi_con_ripiego) — un
        # timeout è a tutti gli effetti un fallimento del provider, non va
        # trattato diversamente da una chiave non valida o una quota esaurita.
        client = OpenAI(api_key=self._api_key, timeout=12.0)
        tools = [{"type": "function", "function": decl} for decl in _function_declarations()]
        messages: list[dict[str, str]] = [{"role": "system", "content": _istruzioni_sistema(context)}]
        # Cronologia dei messaggi recenti (vedi services/conversation_state) —
        # senza, ogni messaggio viene deciso da solo e un riferimento come "e
        # il mese scorso?" non ha modo di essere capito da un LLM vero.
        for turno in context.get("storico", []):
            messages.append({"role": "user" if turno["ruolo"] == "utente" else "assistant", "content": turno["testo"]})
        messages.append({"role": "user", "content": message})

        response = client.chat.completions.create(model=self._model, messages=messages, tools=tools)
        choice = response.choices[0].message
        if choice.tool_calls:
            import json

            call = choice.tool_calls[0]
            arguments = json.loads(call.function.arguments)
            return AgentDecision(tool=call.function.name, confidence=0.85, arguments=arguments, reply=choice.content or "")
        return AgentDecision(tool="none", confidence=0.0, reply=choice.content or "")



class GeminiLLMClient:
    """Client reale (Google Gemini, function calling) — stessa interfaccia e
    stessi due tool di OpenAILLMClient (vedi _function_declarations), a
    differenza di quello VERIFICATA con chiamate reali (vedi PLAN.md, 25
    agosto 2026) prima di diventare quella di default quando GEMINI_API_KEY
    è configurata."""

    def __init__(self, api_key: str, model: str = "gemini-3.6-flash") -> None:
        self._api_key = api_key
        self._model = model

    def decide_action(self, message: str, context: dict[str, Any]) -> AgentDecision:
        import google.generativeai as genai  # import differito: pesante e non necessario in modalità stub

        genai.configure(api_key=self._api_key)
        modello = genai.GenerativeModel(
            self._model,
            tools=[{"function_declarations": _function_declarations()}],
            system_instruction=_istruzioni_sistema(context),
        )
        # Timeout esplicito: verificato dal vivo (3 settembre 2026) che senza
        # questo una risposta lenta/un rate-limit lato Gemini blocca la
        # richiesta HTTP per oltre un minuto invece di far scattare il
        # ripiego su StubLLMClient — un timeout è a tutti gli effetti un
        # fallimento del provider, non va trattato diversamente da una
        # chiave non valida o una quota esaurita (vedi AgentBrain._decidi_con_ripiego).
        risposta = modello.generate_content(
            _contents_da_storico(context.get("storico", []), message),
            request_options={"timeout": 12},
        )

        parte = risposta.candidates[0].content.parts[0]
        function_call = getattr(parte, "function_call", None)
        if function_call and function_call.name:
            arguments = _proto_a_python(function_call.args)
            reply = _reply_di_default(function_call.name, arguments)
            return AgentDecision(tool=function_call.name, confidence=0.85, arguments=arguments, reply=reply)
        return AgentDecision(tool="none", confidence=0.0, reply=risposta.text or "")


_RUOLO_GEMINI = {"utente": "user", "assistente": "model"}


def _contents_da_storico(storico: list[dict[str, str]], message: str) -> list[dict[str, Any]]:
    """Trasforma la cronologia recente (vedi services/conversation_state, già
    passata come lista di dict per non legare llm_client alla dataclass
    Turno) nella forma "contents" multi-turno di Gemini, col messaggio
    corrente come ultimo turno "user" — senza questo, generate_content(message)
    vedeva solo l'ultimo messaggio, senza nessuna nozione di cosa fosse stato
    chiesto prima nella stessa conversazione."""
    contents = [
        {"role": _RUOLO_GEMINI.get(turno["ruolo"], "user"), "parts": [turno["testo"]]}
        for turno in storico
        if turno.get("testo")
    ]
    contents.append({"role": "user", "parts": [message]})
    return contents


def _proto_a_python(valore: Any) -> Any:
    """Gli argomenti di una function_call di Gemini arrivano come strutture
    protobuf (MapComposite/RepeatedComposite), non dict/list nativi Python —
    json non le serializza direttamente. Conversione ricorsiva esplicita
    invece di affidarsi a un dict()/list() superficiale, che lascia gli
    elementi annidati (es. "periodi": [[2026, 7], [2026, 8]]) ancora come
    oggetti protobuf.

    Include anche una correzione non ovvia, trovata solo provando una
    chiamata reale: un campo dichiarato "integer" nello schema (anno, mese)
    torna comunque come float (2026.0) — il tipo Struct di protobuf usato
    da Gemini per gli argomenti non distingue interi da numeri con virgola.
    Un float intero viene quindi convertito a int qui, in un solo posto,
    invece che in ognuna delle funzioni che lo useranno più a valle (dove
    una chiamata come date(2026.0, 7.0, 1) fallirebbe con un TypeError)."""
    if hasattr(valore, "items"):
        return {k: _proto_a_python(v) for k, v in valore.items()}
    if hasattr(valore, "__iter__") and not isinstance(valore, str):
        return [_proto_a_python(v) for v in valore]
    if isinstance(valore, float) and valore.is_integer():
        return int(valore)
    return valore

