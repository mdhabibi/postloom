"""Port for the usage ledger: every model call, so users see what postloom costs them."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class Task(StrEnum):
    """What a model call was for; usage is reported per task."""

    EXTRACTION = "extraction"
    """Restoring an article and its metadata."""
    COMMENTS = "comments"
    """Splitting a pasted comment section into messages."""
    CHAT = "chat"
    REPLY = "reply"
    """Reply drafts."""
    EMBEDDINGS = "embeddings"
    TEST = "test"
    """Connection checks from setup."""


@dataclass(frozen=True, slots=True)
class UsageEntry:
    """Totals for one (month, provider, model, task)."""

    month: str
    """``YYYY-MM`` in UTC."""
    provider: str
    model: str
    task: Task
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    """Exact where the provider reported it, otherwise estimated from the price table."""
    unpriced_calls: int
    """Calls whose cost is unknown (no price for the model); not included in cost_usd."""


def month_of(moment: datetime) -> str:
    return f"{moment.year:04d}-{moment.month:02d}"


class UsageLedger(Protocol):
    def record(
        self,
        *,
        at: datetime,
        provider: str,
        model: str,
        task: Task,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float | None,
    ) -> None:
        """Add one call. ``cost_usd`` None means the price is unknown."""
        ...

    def month(self, month: str) -> Sequence[UsageEntry]:
        """Every entry for ``YYYY-MM``, in a stable order."""
        ...
