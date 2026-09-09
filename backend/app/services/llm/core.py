from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol

@dataclass
class AgentDecision:
    """L'output strutturato che ci si aspetterebbe da un vero LLM con function
    calling: quale tool usare, con quali argomenti, quanto l'IA è sicura
    (soglia di fiducia, Sezione 7 del piano di progetto) e cosa manca per
    poter agire."""

    tool: str  # "email_tool" | "db_connector" | "scraper_tool" | "none"
    confidence: float  # 0..1
    arguments: dict[str, Any] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    reply: str = ""


class LLMClient(Protocol):
    def decide_action(self, message: str, context: dict[str, Any]) -> AgentDecision: ...

