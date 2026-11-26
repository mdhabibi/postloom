from datetime import UTC, datetime

import pytest

from postloom.adapters.export import graph_formats
from postloom.adapters.storage.memory import InMemoryGraphRepository
from postloom.application.errors import ApplicationError
from postloom.application.ports.graph_export import ExportOptions
from postloom.application.use_cases.export_graph import ExportGraph
from postloom.domain.provenance import Grade
from tests.fakes import FixedClock
from tests.graph_library import library


def exporter() -> ExportGraph:
    repository = InMemoryGraphRepository()
    repository.replace_graph(library())
    return ExportGraph(repository, graph_formats(), FixedClock(datetime(2026, 11, 26, tzinfo=UTC)))


def test_the_snapshot_holds_every_node_and_only_live_edges() -> None:
    graph = exporter().snapshot()
    assert len(graph.comments) == 3
    assert [s.name for s in graph.series] == ["Caching in practice"]
    assert all(e.is_current for e in graph.edges)
    assert not any(e.provenance.grade is Grade.REJECTED for e in graph.edges)


def test_with_history_superseded_and_rejected_edges_come_too() -> None:
    graph = exporter().snapshot(history=True)
    assert any(e.superseded_at is not None for e in graph.edges)
    assert any(e.provenance.grade is Grade.REJECTED for e in graph.edges)
    assert len(graph.edges) > len(exporter().snapshot().edges)


def test_an_export_is_named_by_date_and_format() -> None:
    export = exporter().execute("turtle", ExportOptions())
    assert export.filename == "postloom-graph-2026-11-26.ttl"
    assert export.media_type.startswith("text/turtle")
    assert export.nodes == 13
    assert export.content.startswith(b"@prefix pl:")


def test_an_unknown_format_is_refused_with_the_known_ones() -> None:
    with pytest.raises(ApplicationError, match="turtle, jsonld, cypher, graphml"):
        exporter().execute("rdfxml")
