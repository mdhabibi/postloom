"""Graph schema: node kinds, edge kinds and the rules for connecting them."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import NewType

from postloom.domain.errors import InvalidEdgeError
from postloom.domain.provenance import Grade, Provenance

NodeId = NewType("NodeId", str)
"""A stable, human-readable id such as ``article:measuring-what-matters-part-3``."""


class NodeKind(StrEnum):
    TOPIC = "topic"
    SERIES = "series"
    ARTICLE = "article"
    POST = "post"
    COMMENT = "comment"
    PERSON = "person"
    ENTITY = "entity"


def node_id(kind: NodeKind, key: str) -> NodeId:
    return NodeId(f"{kind.value}:{key}")


def kind_of(node: NodeId) -> NodeKind:
    prefix, _, _ = node.partition(":")
    return NodeKind(prefix)


class EdgeKind(StrEnum):
    BELONGS_TO = "belongs_to"  # article | stand-alone post -> topic
    PART_OF = "part_of"  # article -> series
    ANNOUNCES = "announces"  # post -> article
    COMMENTED_ON = "commented_on"  # comment -> post | article
    REPLIED_TO = "replied_to"  # comment -> comment
    AUTHORED = "authored"  # person -> comment
    RELATED_TO = "related_to"  # article -> article (semantic suggestion)
    LINKS_TO = "links_to"  # article | post -> article
    MENTIONS = "mentions"  # article | post -> person | entity (only once the user confirms)


_ALLOWED: dict[EdgeKind, tuple[frozenset[NodeKind], frozenset[NodeKind]]] = {
    EdgeKind.BELONGS_TO: (
        frozenset({NodeKind.ARTICLE, NodeKind.POST}),
        frozenset({NodeKind.TOPIC}),
    ),
    EdgeKind.PART_OF: (frozenset({NodeKind.ARTICLE}), frozenset({NodeKind.SERIES})),
    EdgeKind.ANNOUNCES: (frozenset({NodeKind.POST}), frozenset({NodeKind.ARTICLE})),
    EdgeKind.COMMENTED_ON: (
        frozenset({NodeKind.COMMENT}),
        frozenset({NodeKind.POST, NodeKind.ARTICLE}),
    ),
    EdgeKind.REPLIED_TO: (frozenset({NodeKind.COMMENT}), frozenset({NodeKind.COMMENT})),
    EdgeKind.AUTHORED: (frozenset({NodeKind.PERSON}), frozenset({NodeKind.COMMENT})),
    EdgeKind.RELATED_TO: (frozenset({NodeKind.ARTICLE}), frozenset({NodeKind.ARTICLE})),
    EdgeKind.LINKS_TO: (
        frozenset({NodeKind.ARTICLE, NodeKind.POST}),
        frozenset({NodeKind.ARTICLE}),
    ),
    EdgeKind.MENTIONS: (
        frozenset({NodeKind.ARTICLE, NodeKind.POST}),
        frozenset({NodeKind.PERSON, NodeKind.ENTITY}),
    ),
}


@dataclass(frozen=True, slots=True)
class Edge:
    """A directed, typed relation between two nodes.

    Edges are never deleted when the world changes: they are *superseded*, so history
    stays queryable while retrieval only uses current edges.
    """

    source: NodeId
    target: NodeId
    kind: EdgeKind
    provenance: Provenance
    weight: float | None = None
    """Optional strength, e.g. cosine similarity for semantic edges."""
    superseded_at: datetime | None = None

    def __post_init__(self) -> None:
        sources, targets = _ALLOWED[self.kind]
        source_kind, target_kind = kind_of(self.source), kind_of(self.target)
        if source_kind not in sources or target_kind not in targets:
            raise InvalidEdgeError(
                f"{self.kind.value} cannot connect {source_kind.value} -> {target_kind.value}"
            )
        if self.source == self.target:
            raise InvalidEdgeError(f"self-loop on {self.source}")

    @property
    def key(self) -> tuple[NodeId, NodeId, EdgeKind]:
        """Identity of an edge: at most one current edge per (source, target, kind)."""
        return (self.source, self.target, self.kind)

    @property
    def is_current(self) -> bool:
        return self.superseded_at is None and self.provenance.grade is not Grade.REJECTED

    def supersede(self, at: datetime) -> Edge:
        return replace(self, superseded_at=at)

    def verify(self, at: datetime) -> Edge:
        return replace(self, provenance=self.provenance.verified(at))

    def reject(self, at: datetime) -> Edge:
        return replace(self, provenance=self.provenance.rejected(at))
