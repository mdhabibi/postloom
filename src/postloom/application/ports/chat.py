"""Port for a conversational language model (answers and, later, reply drafts)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    text: str


class ChatModel(Protocol):
    @property
    def name(self) -> str:
        """Producer name, e.g. ``"llm:gemini-3.8-flash"``."""
        ...

    def complete(self, system: str, messages: Sequence[ChatMessage]) -> str:
        """Return the model's next message in plain text (Markdown allowed)."""
        ...
