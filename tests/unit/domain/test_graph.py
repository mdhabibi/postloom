from datetime import UTC, datetime

import pytest

from postloom.domain.errors import InvalidEdgeError
from postloom.domain.graph import Edge, EdgeKind, NodeId, NodeKind, kind_of, node_id
from postloom.domain.provenance import Grade, Origin, Provenance

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2026, 2, 1, tzinfo=UTC)
ARTICLE = node_id(NodeKind.ARTICLE, "part-3")
OTHER_ARTICLE = node_id(NodeKind.ARTICLE, "part-2")
TOPIC = node_id(NodeKind.TOPIC, "rag")
POST = node_id(NodeKind.POST, "part-3")


def asserted() -> Provenance:
    return Provenance(Origin.TAXONOMY, Grade.ASSERTED, "llm:fake", T0)


def test_node_ids_round_trip_their_kind() -> None:
    assert ARTICLE == "article:part-3"
    assert kind_of(ARTICLE) is NodeKind.ARTICLE


@pytest.mark.parametrize(
    ("source", "target", "kind"),
    [
        (TOPIC, ARTICLE, EdgeKind.BELONGS_TO),  # wrong direction
        (POST, TOPIC, EdgeKind.ANNOUNCES),  # post must announce an article
        (ARTICLE, POST, EdgeKind.RELATED_TO),
    ],
)
def test_schema_rejects_invalid_connections(source: NodeId, target: NodeId, kind: EdgeKind) -> None:
    with pytest.raises(InvalidEdgeError):
        Edge(source, target, kind, asserted())


def test_self_loops_are_rejected() -> None:
    with pytest.raises(InvalidEdgeError):
        Edge(ARTICLE, ARTICLE, EdgeKind.RELATED_TO, asserted())


def test_verify_reject_and_supersede_keep_the_edge_identity() -> None:
    edge = Edge(ARTICLE, TOPIC, EdgeKind.BELONGS_TO, asserted())
    assert edge.is_current

    verified = edge.verify(T1)
    assert verified.provenance.grade is Grade.VERIFIED
    assert verified.provenance.producer == "user"
    assert verified.key == edge.key

    rejected = edge.reject(T1)
    assert not rejected.is_current
    assert rejected.superseded_at is None  # rejection is a decision, not history

    retired = edge.supersede(T1)
    assert not retired.is_current
    assert retired.superseded_at == T1


def test_semantic_edges_carry_a_weight() -> None:
    semantic = Provenance(Origin.SEMANTIC, Grade.ASSERTED, "embedding:fake", T0)
    edge = Edge(ARTICLE, OTHER_ARTICLE, EdgeKind.RELATED_TO, semantic, weight=0.87)
    assert edge.weight == pytest.approx(0.87)
