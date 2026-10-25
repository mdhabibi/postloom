"""ChatModel for any provider, with fallback models for when one is overloaded."""

from __future__ import annotations

from collections.abc import Sequence

from postloom.adapters.llm.base import Effort, Turn
from postloom.adapters.llm.gateway import LlmGateway
from postloom.application.errors import ProviderUnavailableError
from postloom.application.ports.chat import ChatMessage, Role
from postloom.application.ports.usage import Task


class LlmChat:
    def __init__(
        self,
        gateway: LlmGateway,
        model: str,
        *,
        task: Task = Task.CHAT,
        fallbacks: Sequence[str] = (),
        max_output_tokens: int = 4096,
        temperature: float = 0.3,
        effort: Effort = "low",
    ) -> None:
        self._gateway = gateway
        self._models = list(dict.fromkeys([model, *fallbacks]))
        self._task = task
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._effort: Effort = effort
        self.last_model: str | None = None
        """Which model produced the most recent answer."""

    @property
    def name(self) -> str:
        return f"llm:{self._models[0]}"

    def complete(self, system: str, messages: Sequence[ChatMessage]) -> str:
        turns: list[Turn] = [
            ("assistant" if m.role is Role.ASSISTANT else "user", m.text) for m in messages
        ]
        busy: list[str] = []
        last: ProviderUnavailableError | None = None
        for model in self._models:
            try:
                text = self._gateway.text(
                    self._task,
                    model,
                    system=system,
                    turns=turns,
                    temperature=self._temperature,
                    max_output_tokens=self._max_output_tokens,
                    effort=self._effort,
                )
            except ProviderUnavailableError as error:
                busy.append(model)
                last = error
                continue
            self.last_model = model
            return text.strip()
        if len(busy) == 1 and last is not None:
            raise last
        raise ProviderUnavailableError(
            f"Every chat model is overloaded or unreachable right now ({', '.join(busy)}). "
            "Try again in a few minutes."
        ) from last
