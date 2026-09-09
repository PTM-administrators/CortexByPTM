from app.core.config import settings
from app.services.llm.core import AgentDecision, LLMClient
from app.services.llm.stub_client import StubLLMClient
from app.services.llm.providers import GeminiLLMClient, OpenAILLMClient

def get_llm_client() -> LLMClient:
    """Sceglie il client in base alla configurazione: nessuna chiave -> stub
    (gratis, per sviluppo/test), altrimenti il primo provider reale
    configurato. Un cambio di `.env`, non di codice."""
    if settings.GEMINI_API_KEY:
        return GeminiLLMClient(api_key=settings.GEMINI_API_KEY)
    if settings.OPENAI_API_KEY:
        return OpenAILLMClient(api_key=settings.OPENAI_API_KEY)
    return StubLLMClient()
