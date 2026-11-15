"""Links between articles: suggested by meaning, decided by the author.

SuggestLinks compares every pair of articles by the centroid of their section embeddings
and proposes ``related_to`` links (semantic, *asserted*) for the closest pairs above a
cutoff. ReviewLink records the author's decision: accepting makes a link *verified*,
dismissing makes it *rejected*, and the author can also link two articles by hand.

The rules that keep the graph trustworthy:
- Suggestions never touch a verified or rejected link, so a dismissed pair is never
  suggested again and an accepted one is never retired.
- A suggestion that no longer passes the cutoff (after an edit or a new embedding model)
  is superseded, not deleted.
- Links are undirected in meaning, so one edge is stored per pair, from the smaller id to
  the larger one, and both directions are checked before adding anything.
- Only accepted links are written to the vault (``related:`` in the article note), so the
  Obsidian graph shows the author's decisions, not the model's guesses.
"""

from __future__ import annotations

import array
import math
import operator
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from postloom.application.errors import ApplicationError
from postloom.application.ports.clock import Clock
from postloom.application.ports.embeddings import EmbeddingProvider, Vector
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.search_index import SearchIndex
from postloom.application.ports.vault import Vault
from postloom.domain.content import Article, Topic
from postloom.domain.graph import Edge, EdgeKind, NodeId, NodeKind, kind_of
from postloom.domain.provenance import Grade, Origin, Provenance

SIMILARITY = "similarity"
"""Producer name for links suggested from embeddings."""

DEFAULT_MAX_SUGGESTIONS = 3
"""Per article: enough to be useful, few enough to review."""


@dataclass(frozen=True, slots=True)
class RelatedLink:
    article_id: NodeId
    title: str
    grade: Grade
    origin: Origin
    similarity: float | None


@dataclass(frozen=True, slots=True)
class PairScore:
    first: NodeId
    second: NodeId
    similarity: float


@dataclass(frozen=True, slots=True)
class SuggestResult:
    added: int
    updated: int
    retired: int
    pairs: tuple[PairScore, ...]
    """Every compared pair, most similar first (for ``--explain`` and calibration)."""
    semantic: bool
    """False when there is no embedding provider, so nothing could be compared."""
    compared: int = 0
    """Articles that had embeddings in the current vector space."""
    articles: int = 0


# -- reading -------------------------------------------------------------------------
def pair_key(a: NodeId, b: NodeId) -> tuple[NodeId, NodeId]:
    return (a, b) if a < b else (b, a)


def related_edges(repository: GraphRepository, article_id: NodeId) -> list[Edge]:
    """Every non-superseded related_to edge touching this article, rejected ones included."""
    edges = [*repository.edges_from(article_id), *repository.edges_to(article_id)]
    return [e for e in edges if e.kind is EdgeKind.RELATED_TO and e.superseded_at is None]


def related_links(repository: GraphRepository, article_id: NodeId) -> list[RelatedLink]:
    """Accepted links first, then suggestions by similarity. Dismissed links are hidden."""
    links: list[RelatedLink] = []
    for edge in related_edges(repository, article_id):
        if not edge.is_current:
            continue
        other_id = edge.target if edge.source == article_id else edge.source
        other = repository.get_article(other_id)
        if other is not None:
            prov = edge.provenance
            links.append(RelatedLink(other.id, other.title, prov.grade, prov.origin, edge.weight))
    links.sort(key=lambda link: (link.grade is not Grade.VERIFIED, -(link.similarity or 0.0)))
    return links


def accepted_related(repository: GraphRepository, article_id: NodeId) -> list[Article]:
    return [
        article
        for link in related_links(repository, article_id)
        if link.grade is Grade.VERIFIED
        if (article := repository.get_article(link.article_id)) is not None
    ]


def rewrite_article_note(repository: GraphRepository, vault: Vault, article_id: NodeId) -> None:
    """Rewrite an article's note from the graph, e.g. after its links changed."""
    article = repository.get_article(article_id)
    if article is None:
        return
    post = next(
        (
            post
            for edge in repository.edges_to(article_id)
            if edge.kind is EdgeKind.ANNOUNCES and edge.is_current
            if (post := repository.get_post(edge.source)) is not None
        ),
        None,
    )
    if post is None:
        return
    taxonomy = {t.id: t for t in repository.list_topics()}
    topics: list[Topic] = [
        taxonomy[edge.target]
        for edge in repository.edges_from(article_id)
        if edge.kind is EdgeKind.BELONGS_TO and edge.is_current and edge.target in taxonomy
    ]
    vault.write_article(article, post, topics, accepted_related(repository, article_id))


# -- suggesting ----------------------------------------------------------------------
class SuggestLinks:
    def __init__(
        self,
        repository: GraphRepository,
        index: SearchIndex,
        embedder: EmbeddingProvider | None,
        clock: Clock,
        min_similarity: float,
        max_per_article: int = DEFAULT_MAX_SUGGESTIONS,
    ) -> None:
        self._repository = repository
        self._index = index
        self._embedder = embedder
        self._clock = clock
        self._min_similarity = min_similarity
        self._max_per_article = max_per_article

    def execute(self) -> SuggestResult:
        if self._embedder is None:
            return SuggestResult(0, 0, 0, (), semantic=False)
        articles = {a.id for a in self._repository.list_articles()}
        grouped = self._index.vectors_by_node(self._embedder.name)
        centroids = {
            node: centroid
            for node, vectors in grouped.items()
            if node in articles
            if (centroid := _centroid(vectors)) is not None
        }
        pairs = _all_pairs(centroids)
        wanted = self._choose(pairs)
        return replace(self._apply(wanted, pairs), compared=len(centroids), articles=len(articles))

    def _choose(self, pairs: list[PairScore]) -> dict[tuple[NodeId, NodeId], float]:
        """Each article keeps its closest neighbours above the cutoff; a pair is wanted
        if either side keeps it."""
        neighbours: dict[NodeId, list[PairScore]] = {}
        for pair in pairs:
            if pair.similarity < self._min_similarity:
                continue
            neighbours.setdefault(pair.first, []).append(pair)
            neighbours.setdefault(pair.second, []).append(pair)
        wanted: dict[tuple[NodeId, NodeId], float] = {}
        for scored in neighbours.values():
            for pair in scored[: self._max_per_article]:  # pairs are sorted already
                wanted[(pair.first, pair.second)] = pair.similarity
        return wanted

    def _apply(
        self, wanted: dict[tuple[NodeId, NodeId], float], pairs: list[PairScore]
    ) -> SuggestResult:
        now = self._clock.now()
        existing: dict[tuple[NodeId, NodeId], Edge] = {}
        for article in self._repository.list_articles():
            for edge in related_edges(self._repository, article.id):
                existing.setdefault(pair_key(edge.source, edge.target), edge)

        added = updated = retired = 0
        for key, edge in existing.items():
            if edge.provenance.grade is not Grade.ASSERTED or key in wanted:
                continue
            self._repository.supersede_edge(edge.supersede(now))
            retired += 1
        for key, similarity in wanted.items():
            old = existing.get(key)
            if old is not None and old.provenance.grade is not Grade.ASSERTED:
                continue  # the author decided; never second-guess it
            if old is not None and old.weight is not None and abs(old.weight - similarity) < 1e-3:
                continue
            evidence = f"meaning similarity {similarity:.3f}"
            provenance = Provenance(Origin.SEMANTIC, Grade.ASSERTED, SIMILARITY, now, evidence)
            edge = Edge(key[0], key[1], EdgeKind.RELATED_TO, provenance, weight=similarity)
            if old is not None:
                self._repository.supersede_edge(old.supersede(now))
                updated += 1
            else:
                added += 1
            self._repository.save_edge(edge)
        return SuggestResult(added, updated, retired, tuple(pairs), semantic=True)


def _centroid(vectors: Sequence[Vector]) -> array.array[float] | None:
    if not vectors:
        return None
    total = [0.0] * len(vectors[0])
    for vector in vectors:
        for i, value in enumerate(vector):
            total[i] += value
    norm = math.sqrt(sum(v * v for v in total))
    return array.array("f", (v / norm for v in total)) if norm else None


def _all_pairs(centroids: dict[NodeId, array.array[float]]) -> list[PairScore]:
    nodes = sorted(centroids)
    pairs = [
        PairScore(a, b, round(sum(map(operator.mul, centroids[a], centroids[b])), 6))
        for i, a in enumerate(nodes)
        for b in nodes[i + 1 :]
    ]
    pairs.sort(key=lambda p: -p.similarity)
    return pairs


# -- reviewing -----------------------------------------------------------------------
class Decision(StrEnum):
    ACCEPT = "accept"
    """Keep a suggested link, or link two articles by hand."""
    REJECT = "reject"
    """Dismiss a suggestion or remove a link; it will not be suggested again."""


def decide_link(
    repository: GraphRepository,
    first: NodeId,
    second: NodeId,
    decision: Decision,
    now: datetime,
    producer: str = "user",
) -> Edge:
    """Record the author's decision about a pair of articles and return the new edge.

    The previous state of the pair (a suggestion, or an earlier decision) moves to
    history. ``producer`` says where the decision was made: in the app (``"user"``) or by
    editing a note (``"vault"``).
    """
    key = pair_key(first, second)
    old = next(
        (e for e in related_edges(repository, first) if pair_key(e.source, e.target) == key),
        None,
    )
    if old is not None:
        repository.supersede_edge(old.supersede(now))
        base = Edge(old.source, old.target, old.kind, old.provenance, weight=old.weight)
    else:
        manual = Provenance(Origin.MANUAL, Grade.ASSERTED, producer, now)
        base = Edge(key[0], key[1], EdgeKind.RELATED_TO, manual)
    provenance = (
        base.provenance.verified(now, producer)
        if decision is Decision.ACCEPT
        else base.provenance.rejected(now, producer)
    )
    edge = replace(base, provenance=provenance)
    repository.save_edge(edge)
    return edge


class ReviewLink:
    def __init__(self, repository: GraphRepository, vault: Vault, clock: Clock) -> None:
        self._repository = repository
        self._vault = vault
        self._clock = clock

    def execute(self, first: NodeId, second: NodeId, decision: Decision) -> RelatedLink:
        for node in (first, second):
            if kind_of_or_none(node) is not NodeKind.ARTICLE:
                raise ApplicationError(f"Not an article: {node}")
            if self._repository.get_article(node) is None:
                raise ApplicationError(f"Unknown article: {node}")
        if first == second:
            raise ApplicationError("An article can't be linked to itself.")

        key = pair_key(first, second)
        edge = decide_link(self._repository, first, second, decision, self._clock.now())

        for node in key:
            rewrite_article_note(self._repository, self._vault, node)
        other = self._repository.get_article(second)
        assert other is not None
        return RelatedLink(
            other.id, other.title, edge.provenance.grade, edge.provenance.origin, edge.weight
        )


def kind_of_or_none(node: NodeId) -> NodeKind | None:
    try:
        return kind_of(node)
    except ValueError:
        return None
