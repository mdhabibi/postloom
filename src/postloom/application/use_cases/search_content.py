"""SearchContent: hybrid keyword + semantic search, results grouped by article.

Keyword search (BM25) is precise for names and exact terms ("LangGraph", "MinHash");
semantic search finds passages that mean the same thing in other words ("my test score
was too optimistic" -> data leakage). Reciprocal rank fusion combines the two rankings
without having to calibrate their incompatible scores against each other.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from postloom.application.errors import ProviderError
from postloom.application.ports.embeddings import EmbeddingProvider
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.search_index import ChunkHit, SearchIndex
from postloom.domain.graph import NodeId
from postloom.domain.text import excerpt

RRF_K = 60
"""Standard reciprocal-rank-fusion constant; dampens the advantage of the very top ranks."""
CANDIDATES_PER_METHOD = 30
PASSAGES_PER_RESULT = 2


class Method(StrEnum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"


@dataclass(frozen=True, slots=True)
class Passage:
    heading: str
    excerpt: str
    chunk_index: int
    matched_by: frozenset[Method]


@dataclass(frozen=True, slots=True)
class SearchResult:
    article_id: NodeId
    title: str
    url: str | None
    score: float
    passages: tuple[Passage, ...]


@dataclass(frozen=True, slots=True)
class SearchResults:
    query: str
    results: tuple[SearchResult, ...]
    methods: frozenset[Method]
    """Which methods actually ran (semantic is skipped without an embedding provider)."""
    warnings: tuple[str, ...] = field(default=())


class SearchContent:
    def __init__(
        self,
        index: SearchIndex,
        repository: GraphRepository,
        embedder: EmbeddingProvider | None,
    ) -> None:
        self._index = index
        self._repository = repository
        self._embedder = embedder

    def execute(self, query: str, limit: int = 5) -> SearchResults:
        query = query.strip()
        if not query:
            return SearchResults(query, (), frozenset())

        warnings: list[str] = []
        rankings: dict[Method, Sequence[ChunkHit]] = {
            Method.KEYWORD: self._index.keyword_search(query, CANDIDATES_PER_METHOD)
        }
        if self._embedder is not None:
            try:
                vector = self._embedder.embed_query(query)
                rankings[Method.SEMANTIC] = self._index.vector_search(
                    vector, self._embedder.name, CANDIDATES_PER_METHOD
                )
            except ProviderError as error:
                warnings.append(f"Semantic search unavailable, showing keyword matches: {error}")

        results = self._fuse(query, rankings)[:limit]
        return SearchResults(query, tuple(results), frozenset(rankings), tuple(warnings))

    def _fuse(self, query: str, rankings: dict[Method, Sequence[ChunkHit]]) -> list[SearchResult]:
        scores: dict[tuple[NodeId, int], float] = defaultdict(float)
        methods: dict[tuple[NodeId, int], set[Method]] = defaultdict(set)
        hits: dict[tuple[NodeId, int], ChunkHit] = {}
        for method, ranked in rankings.items():
            for rank, hit in enumerate(ranked, start=1):
                key = (hit.node, hit.index)
                scores[key] += 1.0 / (RRF_K + rank)
                methods[key].add(method)
                hits[key] = hit

        by_article: dict[NodeId, list[tuple[float, ChunkHit]]] = defaultdict(list)
        for key, score in scores.items():
            by_article[key[0]].append((score, hits[key]))

        results: list[SearchResult] = []
        for node, scored in by_article.items():
            scored.sort(key=lambda item: item[0], reverse=True)
            top = scored[:PASSAGES_PER_RESULT]
            article = self._repository.get_article(node)
            passages = tuple(
                Passage(
                    heading=hit.heading,
                    excerpt=excerpt(hit.text, query),
                    chunk_index=hit.index,
                    matched_by=frozenset(methods[(hit.node, hit.index)]),
                )
                for _, hit in top
            )
            results.append(
                SearchResult(
                    article_id=node,
                    title=article.title if article else top[0][1].title,
                    url=article.url if article else None,
                    # The best passage decides; a second strong passage adds a little.
                    score=top[0][0] + sum(s for s, _ in top[1:]) * 0.25,
                    passages=passages,
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results
