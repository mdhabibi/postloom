from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Source of the current time, injected so tests are deterministic."""

    def now(self) -> datetime: ...
