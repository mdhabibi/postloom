"""Port for turning text into vectors for semantic search."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

Vector = list[float]


@dataclass(frozen=True, slots=True)
class DocumentText:
    """A piece of content to embed, with the title that gives it context."""

    title: str
    text: str


class EmbeddingProvider(Protocol):
    @property
    def name(self) -> str:
        """Identifies the vector space, e.g. ``"gemini-embedding-2@768"``.

        Vectors from different names are incompatible and are never compared.
        """
        ...

    def embed_documents(self, documents: Sequence[DocumentText]) -> list[Vector]:
        """Embed content for storage. Returns unit-length vectors, in input order."""
        ...

    def embed_query(self, query: str) -> Vector:
        """Embed a search query. Returns a unit-length vector."""
        ...
