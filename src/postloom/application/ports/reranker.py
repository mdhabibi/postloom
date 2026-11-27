"""Re-scoring the passages search found, by reading question and passage together."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class Reranker(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def relevant_score(self) -> float:
        """The lowest score at which a passage counts as answering the question."""
        ...

    def scores(self, query: str, passages: Sequence[str]) -> list[float]:
        """One relevance score per passage, in order; higher is more relevant. Scores are
        only comparable for the same reranker. Raises ProviderError when it can't run."""
        ...
