"""ChatModel backed by Gemini."""

from __future__ import annotations

from collections.abc import Sequence

from postloom.adapters.llm.gemini import GeminiClient
from postloom.application.ports.chat import ChatMessage, Role


class GeminiChat:
    def __init__(self, client: GeminiClient, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def name(self) -> str:
        return f"llm:{self._model}"

    def complete(self, system: str, messages: Sequence[ChatMessage]) -> str:
        turns = [("model" if m.role is Role.ASSISTANT else "user", m.text) for m in messages]
        return self._client.generate_text(self._model, system=system, turns=turns).strip()
