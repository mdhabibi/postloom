"""ChatModel backed by Gemini, with fallback models for busy periods.

Popular Gemini models are sometimes overloaded ("high demand", HTTP 503/429) for minutes
at a time. Rather than failing the user's question, the chat tries the next model in its
list. The fallbacks are cheaper, lighter models that are rarely saturated.
"""

from __future__ import annotations

from collections.abc import Sequence

from postloom.adapters.llm.gemini import GeminiClient
from postloom.application.errors import ProviderUnavailableError
from postloom.application.ports.chat import ChatMessage, Role


class GeminiChat:
    def __init__(self, client: GeminiClient, model: str, fallbacks: Sequence[str] = ()) -> None:
        self._client = client
        self._models = list(dict.fromkeys([model, *fallbacks]))
        self.last_model: str | None = None
        """Which model produced the most recent answer."""

    @property
    def name(self) -> str:
        return f"llm:{self._models[0]}"

    def complete(self, system: str, messages: Sequence[ChatMessage]) -> str:
        turns = [("model" if m.role is Role.ASSISTANT else "user", m.text) for m in messages]
        busy: list[str] = []
        for model in self._models:
            try:
                text = self._client.generate_text(model, system=system, turns=turns)
            except ProviderUnavailableError:
                busy.append(model)
                continue
            self.last_model = model
            return text.strip()
        raise ProviderUnavailableError(
            f"Gemini is overloaded right now ({', '.join(busy)} all busy). "
            "Try again in a few minutes."
        )
