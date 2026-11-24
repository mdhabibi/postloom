"""Where found-but-unconfirmed mentions wait for the user.

A pending review is a cache, not the user's data: it can always be found again, so it
lives in the index and not in the vault. What the user decides is in the graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from postloom.domain.graph import NodeId


@dataclass(frozen=True, slots=True)
class Suggestion:
    name: str
    category: str
    """``person`` or an entity category (``organisation``, ``link``...)."""
    evidence: str = ""
    url: str | None = None
    match: NodeId | None = None
    """Something already in the graph this is probably the same as."""
    match_name: str | None = None
    match_note: str | None = None


@dataclass(frozen=True, slots=True)
class TopicSuggestion:
    name: str
    exists: bool


@dataclass(frozen=True, slots=True)
class Review:
    item: NodeId
    suggestions: tuple[Suggestion, ...]
    topics: tuple[TopicSuggestion, ...]
    found_at: datetime
    finder: str | None
    """The model that read the text, or None when only links were looked for."""
    dismissed: tuple[str, ...] = ()
    """Names the user said no to here, so finding again doesn't bring them back."""

    @property
    def is_empty(self) -> bool:
        return not self.suggestions and not self.topics


class ReviewStore(Protocol):
    def get(self, item: NodeId) -> Review | None: ...

    def put(self, review: Review) -> None: ...

    def remove(self, item: NodeId) -> None: ...

    def pending(self) -> list[Review]:
        """Reviews that still have something to decide, newest first."""
        ...
