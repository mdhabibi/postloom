"""Provenance: every fact in the graph records where it came from and how sure we are.

A link suggested by a model starts as ASSERTED and only becomes VERIFIED when the user
accepts it. Chat answers can then cite the exact source of each fact, and the UI can show
which parts of the graph are still unreviewed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class Grade(StrEnum):
    """How much we trust a fact."""

    VERIFIED = "verified"
    """Confirmed by a deterministic rule or by the user."""

    ASSERTED = "asserted"
    """Stated by a model or a heuristic and not yet reviewed."""

    REJECTED = "rejected"
    """Reviewed by the user and declined. Kept so it is not suggested again."""


class Origin(StrEnum):
    """Which mechanism produced a fact."""

    STRUCTURAL = "structural"
    """Parsed deterministically from the content (a post announcing its article)."""

    TAXONOMY = "taxonomy"
    """A model classified content into the user's fixed topic list."""

    SEMANTIC = "semantic"
    """Embedding similarity above a threshold."""

    MANUAL = "manual"
    """Created by the user in the UI or the vault."""


@dataclass(frozen=True, slots=True)
class Provenance:
    origin: Origin
    grade: Grade
    producer: str
    """Who produced it, e.g. ``"parser"``, ``"llm:gemini-2.5-flash"``, ``"user"``."""
    recorded_at: datetime
    evidence: str | None = None
    """Optional excerpt or reason supporting the fact, shown when citing it."""

    def verified(self, at: datetime, producer: str = "user") -> Provenance:
        return replace(self, grade=Grade.VERIFIED, producer=producer, recorded_at=at)

    def rejected(self, at: datetime, producer: str = "user") -> Provenance:
        return replace(self, grade=Grade.REJECTED, producer=producer, recorded_at=at)
