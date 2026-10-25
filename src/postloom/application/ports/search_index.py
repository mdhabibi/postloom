"""Port for the retrieval index: keyword and vector search over content chunks.

Like the graph repository, the index is derived data and can always be rebuilt from the
vault. Implementations must pass ``tests/contract/test_search_index.py``.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from postloom.application.ports.embeddings import Vector
from postloom.domain.chunking import Chunk
from postloom.domain.graph import NodeId


@dataclass(frozen=True, slots=True)
class IndexedChunk:
    chunk: Chunk
    vector: Vector | None
    """None when no embedding provider is configured; keyword search still works."""
    vector_space: str | None


@dataclass(frozen=True, slots=True)
class ChunkHit:
    node: NodeId
    index: int
    heading: str
    text: str
    title: str
    score: float
    """Higher is better. Only comparable within one search method."""


class SearchIndex(Protocol):
    def replace_chunks(self, node: NodeId, chunks: Sequence[IndexedChunk]) -> None:
        """Atomically replace everything indexed for ``node`` with ``chunks``."""
        ...

    def remove(self, node: NodeId) -> None: ...

    def cached_vectors(self, space: str, hashes: Collection[str]) -> dict[str, Vector]:
        """Stored vectors for chunks with these content hashes, in this vector space."""
        ...

    def chunks_of(self, node: NodeId) -> Sequence[ChunkHit]:
        """Every chunk indexed for ``node``, in document order (score 0)."""
        ...

    def vectors_by_node(self, space: str) -> Mapping[NodeId, Sequence[Vector]]:
        """Every stored vector in this vector space, grouped by the node it belongs to."""
        ...

    def vector_spaces(self) -> Mapping[str, int]:
        """How many chunks have vectors in each vector space."""
        ...

    def keyword_search(self, query: str, limit: int) -> Sequence[ChunkHit]: ...

    def vector_search(self, vector: Vector, space: str, limit: int) -> Sequence[ChunkHit]: ...
