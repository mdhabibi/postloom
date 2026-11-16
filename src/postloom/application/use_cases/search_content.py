"""SearchContent: hybrid keyword + semantic search, results grouped by article.

Articles, their announcement posts and the comment threads under them are all searched;
a match in a post or a comment is shown under the article it belongs to.

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
from postloom.application.use_cases.index_content import COMMENTS_HEADING
from postloom.application.use_cases.relations import get_item, item_of_post
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
    similarity: float | None = None
    """Cosine similarity to the query (semantic match), for explaining results."""
    keyword_score: float | None = None
    """BM25 relevance (keyword match), for explaining results."""
    kind: str = "article"
    """Where the passage is from: "article", "post" or "comments"."""


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
        min_similarity: float = 0.0,
    ) -> None:
        self._index = index
        self._repository = repository
        self._embedder = embedder
        self._min_similarity = min_similarity
        """Semantic matches below this cosine similarity are dropped as unrelated."""

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
                nearest = self._index.vector_search(
                    vector, self._embedder.name, CANDIDATES_PER_METHOD
                )
                rankings[Method.SEMANTIC] = [
                    hit for hit in nearest if hit.score >= self._min_similarity
                ]
            except ProviderError as error:
                warnings.append(f"Semantic search unavailable, showing keyword matches: {error}")

        results = self._fuse(query, rankings)[:limit]
        return SearchResults(query, tuple(results), frozenset(rankings), tuple(warnings))

    def _fuse(self, query: str, rankings: dict[Method, Sequence[ChunkHit]]) -> list[SearchResult]:
        scores: dict[tuple[NodeId, int], float] = defaultdict(float)
        raw: dict[tuple[NodeId, int], dict[Method, float]] = defaultdict(dict)
        hits: dict[tuple[NodeId, int], ChunkHit] = {}
        for method, ranked in rankings.items():
            for rank, hit in enumerate(ranked, start=1):
                key = (hit.node, hit.index)
                scores[key] += 1.0 / (RRF_K + rank)
                raw[key][method] = hit.score
                hits[key] = hit

        by_article: dict[NodeId, list[tuple[float, ChunkHit]]] = defaultdict(list)
        for key, score in scores.items():
            article_id = article_for(self._repository, key[0])
            if article_id is not None:
                by_article[article_id].append((score, hits[key]))

        results: list[SearchResult] = []
        for node, scored in by_article.items():
            scored.sort(key=lambda item: item[0], reverse=True)
            top = scored[:PASSAGES_PER_RESULT]
            article = get_item(self._repository, node)
            passages = tuple(
                Passage(
                    heading=hit.heading,
                    excerpt=excerpt(hit.text, query),
                    chunk_index=hit.index,
                    matched_by=frozenset(raw[(hit.node, hit.index)]),
                    similarity=raw[(hit.node, hit.index)].get(Method.SEMANTIC),
                    keyword_score=raw[(hit.node, hit.index)].get(Method.KEYWORD),
                    kind=passage_kind(hit),
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


def article_for(repository: GraphRepository, node: NodeId) -> NodeId | None:
    """The library item an indexed node belongs to: an article itself, the article a post
    announces, or a post that stands on its own."""
    if node.startswith("post:"):
        item = item_of_post(repository, node)
        return item.id if item is not None else None
    return node


def passage_kind(hit: ChunkHit) -> str:
    if not hit.node.startswith("post:"):
        return "article"
    return "comments" if hit.heading.startswith(COMMENTS_HEADING) else "post"
